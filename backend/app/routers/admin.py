"""Vendors, the parts list, and expenses."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, BeforeValidator, EmailStr, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core import audit
from app.core.deps import require_user
from app.core.errors import NotFound
from app.db import get_db
from app.models import Expense, Part, User, Vendor
from app.models.admin import EXPENSE_CATEGORIES
from app.schemas.common import ShortText, _strip
from app.services import photos, workflow
from app.services.business import get_business, shop_today

router = APIRouter(tags=["parts, vendors & expenses"])

Name = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=120)]
Cents = Annotated[int, Field(ge=0, le=100_000_000)]
Qty = Annotated[Decimal, Field(ge=-100_000, le=100_000, max_digits=10, decimal_places=2)]
OptEmail = Annotated[EmailStr | None, BeforeValidator(_strip)]


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _audit_changes(db, user, action, entity_type, entity_id, before, after):
    delta = audit.diff(before, after)
    if delta:
        audit.record(
            db,
            user=user,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=delta,
        )


# ------------------------------------------------------------------ vendors


class VendorIn(BaseModel):
    name: Name
    phone: ShortText(40) = None
    email: OptEmail = None
    website: ShortText(300) = None
    account_number: ShortText(80) = None
    notes: ShortText(2000) = None


class VendorUpdate(VendorIn):
    name: Annotated[str | None, BeforeValidator(_strip), Field(min_length=1, max_length=120)] = None


def vendor_out(v: Vendor) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "phone": v.phone,
        "email": v.email,
        "website": v.website,
        "account_number": v.account_number,
        "notes": v.notes,
        "archived_at": v.archived_at,
    }


@router.get("/vendors")
def list_vendors(
    archived: bool = False, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    q = select(Vendor).order_by(func.lower(Vendor.name))
    q = q.where(Vendor.archived_at.is_not(None) if archived else Vendor.archived_at.is_(None))
    return [vendor_out(v) for v in db.scalars(q)]


@router.post("/vendors", status_code=201)
def create_vendor(
    data: VendorIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    v = Vendor(**data.model_dump())
    db.add(v)
    db.flush()
    audit.record(db, user=user, action="vendor.created", entity_type="vendor", entity_id=v.id)
    return vendor_out(v)


@router.patch("/vendors/{vendor_id}")
def update_vendor(
    vendor_id: int,
    data: VendorUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    v = workflow.get_or_404(db, Vendor, vendor_id, "Vendor")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name", "") is None:
        changes.pop("name")
    before = {k: getattr(v, k) for k in changes}
    for k, val in changes.items():
        setattr(v, k, val)
    _audit_changes(db, user, "vendor.updated", "vendor", v.id, before, changes)
    return vendor_out(v)


@router.post("/vendors/{vendor_id}/archive")
def archive_vendor(
    vendor_id: int,
    restore: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    v = workflow.get_or_404(db, Vendor, vendor_id, "Vendor")
    v.archived_at = None if restore else datetime.now(UTC)
    return vendor_out(v)


# ------------------------------------------------------------------ parts


class PartIn(BaseModel):
    name: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=200)]
    part_number: ShortText(80) = None
    category: ShortText(60) = None
    vendor_id: int | None = None
    cost_cents: Cents | None = None
    price_cents: Cents | None = None
    quantity: Qty | None = None
    reorder_at: Annotated[Decimal, Field(ge=0, le=100_000, decimal_places=2)] | None = None
    warranty_months: Annotated[int, Field(ge=0, le=600)] | None = None
    warranty_miles: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    warranty_notes: ShortText(300) = None
    notes: ShortText(2000) = None

    @model_validator(mode="after")
    def priced(self):
        if self.cost_cents is None and self.price_cents is None:
            raise ValueError("Enter a cost, a customer price, or both.")
        return self


class PartUpdate(PartIn):
    name: Annotated[str | None, BeforeValidator(_strip), Field(min_length=1, max_length=200)] = None

    @model_validator(mode="after")
    def priced(self):
        return self


def part_out(p: Part, markup: Decimal) -> dict:
    from app.core.pricing import price_from_markup

    price = p.price_cents
    if price is None and p.cost_cents is not None:
        price = price_from_markup(p.cost_cents, markup)
    tracked = p.quantity is not None
    return {
        "id": p.id,
        "name": p.name,
        "part_number": p.part_number,
        "category": p.category,
        "vendor_id": p.vendor_id,
        "vendor_name": p.vendor.name if p.vendor else None,
        "cost_cents": p.cost_cents,
        "price_cents": p.price_cents,
        "effective_price_cents": price,
        "price_from_markup": p.price_cents is None,
        "quantity": p.quantity,
        "reorder_at": p.reorder_at,
        "low_stock": tracked and p.reorder_at is not None and p.quantity <= p.reorder_at,
        "warranty_months": p.warranty_months,
        "warranty_miles": p.warranty_miles,
        "warranty_notes": p.warranty_notes,
        "notes": p.notes,
        "archived_at": p.archived_at,
    }


def _check_vendor(db: Session, vendor_id: int | None) -> None:
    if vendor_id is not None and db.get(Vendor, vendor_id) is None:
        raise workflow.InvalidReference("That vendor wasn't found.")


@router.get("/parts")
def list_parts(
    q: Annotated[str | None, Query(max_length=100)] = None,
    low_stock: bool = False,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    query = select(Part).options(joinedload(Part.vendor))
    query = query.where(Part.archived_at.is_not(None) if archived else Part.archived_at.is_(None))
    if q and q.strip():
        like = _like(q.strip())
        query = query.where(
            or_(
                Part.name.ilike(like, escape="\\"),
                Part.part_number.ilike(like, escape="\\"),
                Part.category.ilike(like, escape="\\"),
            )
        )
    if low_stock:
        query = query.where(
            Part.quantity.is_not(None),
            Part.reorder_at.is_not(None),
            Part.quantity <= Part.reorder_at,
        )
    markup = get_business(db).default_parts_markup_pct
    rows = db.scalars(query.order_by(func.lower(Part.name)).limit(limit))
    return [part_out(p, markup) for p in rows]


@router.post("/parts", status_code=201)
def create_part(data: PartIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _check_vendor(db, data.vendor_id)
    p = Part(**data.model_dump())
    db.add(p)
    db.flush()
    audit.record(
        db,
        user=user,
        action="part.created",
        entity_type="part",
        entity_id=p.id,
        details={"name": p.name, "quantity": str(p.quantity) if p.quantity is not None else None},
    )
    db.refresh(p)
    return part_out(p, get_business(db).default_parts_markup_pct)


@router.patch("/parts/{part_id}")
def update_part(
    part_id: int,
    data: PartUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    p = workflow.get_or_404(db, Part, part_id, "Part", lock=True)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name", "") is None:
        changes.pop("name")
    if "vendor_id" in changes:
        _check_vendor(db, changes["vendor_id"])
    before = {k: getattr(p, k) for k in changes}
    for k, val in changes.items():
        setattr(p, k, val)
    _audit_changes(db, user, "part.updated", "part", p.id, before, changes)
    db.flush()
    db.refresh(p)
    return part_out(p, get_business(db).default_parts_markup_pct)


class StockAdjust(BaseModel):
    change: Annotated[Decimal, Field(ge=-10_000, le=10_000, decimal_places=2)]
    reason: ShortText(200) = None


@router.post("/parts/{part_id}/stock")
def adjust_stock(
    part_id: int,
    data: StockAdjust,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Received an order (+) or corrected a count (-/+). Starts tracking if it wasn't."""
    p = workflow.get_or_404(db, Part, part_id, "Part", lock=True)
    p.quantity = (p.quantity or Decimal("0")) + data.change
    audit.record(
        db,
        user=user,
        action="part.stock_adjusted",
        entity_type="part",
        entity_id=p.id,
        details={"change": str(data.change), "now": str(p.quantity), "reason": data.reason},
    )
    db.flush()
    db.refresh(p)
    return part_out(p, get_business(db).default_parts_markup_pct)


@router.post("/parts/{part_id}/archive")
def archive_part(
    part_id: int,
    restore: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    p = workflow.get_or_404(db, Part, part_id, "Part")
    p.archived_at = None if restore else datetime.now(UTC)
    return part_out(p, get_business(db).default_parts_markup_pct)


# ------------------------------------------------------------------ expenses

Category = Literal[EXPENSE_CATEGORIES]  # type: ignore[valid-type]


class ExpenseIn(BaseModel):
    expense_date: date
    category: Category
    amount_cents: Annotated[int, Field(gt=0, le=100_000_000)]
    vendor_id: int | None = None
    vendor_name: ShortText(120) = None
    description: ShortText(500) = None


class ExpenseUpdate(BaseModel):
    expense_date: date | None = None
    category: Category | None = None
    amount_cents: Annotated[int, Field(gt=0, le=100_000_000)] | None = None
    vendor_id: int | None = None
    vendor_name: ShortText(120) = None
    description: ShortText(500) = None


def expense_out(e: Expense, receipts: list) -> dict:
    return {
        "id": e.id,
        "expense_date": e.expense_date,
        "category": e.category,
        "amount_cents": e.amount_cents,
        "vendor_id": e.vendor_id,
        "vendor_name": e.vendor.name if e.vendor else e.vendor_name,
        "description": e.description,
        "receipts": [photos.photo_out(p) for p in receipts],
        "created_at": e.created_at,
    }


def _expense(db: Session, expense_id: int) -> Expense:
    e = db.get(Expense, expense_id)
    if e is None or e.deleted_at is not None:
        raise NotFound("Expense not found.")
    return e


@router.get("/expenses")
def list_expenses(
    start: date | None = None,
    end: date | None = None,
    category: Category | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    """Defaults to the current month. Includes totals by category for the same filter."""
    today = shop_today(get_business(db))
    start = start or today.replace(day=1)
    end = end or today
    where = [
        Expense.deleted_at.is_(None),
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ]
    if category:
        where.append(Expense.category == category)
    rows = list(
        db.scalars(
            select(Expense)
            .options(joinedload(Expense.vendor))
            .where(*where)
            .order_by(Expense.expense_date.desc(), Expense.id.desc())
        )
    )
    receipts = photos.photos_for(db, "expense", [e.id for e in rows])
    by_cat: dict[str, int] = {}
    for e in rows:
        by_cat[e.category] = by_cat.get(e.category, 0) + e.amount_cents
    return {
        "start": start,
        "end": end,
        "items": [expense_out(e, receipts[e.id]) for e in rows],
        "total_cents": sum(by_cat.values()),
        "by_category": by_cat,
    }


@router.post("/expenses", status_code=201)
def create_expense(
    data: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    _check_vendor(db, data.vendor_id)
    e = Expense(**data.model_dump(), created_by_user_id=user.id)
    db.add(e)
    db.flush()
    audit.record(
        db,
        user=user,
        action="expense.created",
        entity_type="expense",
        entity_id=e.id,
        details={"amount_cents": e.amount_cents, "category": e.category},
    )
    db.refresh(e)
    return expense_out(e, [])


@router.patch("/expenses/{expense_id}")
def update_expense(
    expense_id: int,
    data: ExpenseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    e = _expense(db, expense_id)
    changes = data.model_dump(exclude_unset=True)
    for required in ("expense_date", "category", "amount_cents"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    if "vendor_id" in changes:
        _check_vendor(db, changes["vendor_id"])
    before = {k: getattr(e, k) for k in changes}
    for k, val in changes.items():
        setattr(e, k, val)
    _audit_changes(db, user, "expense.updated", "expense", e.id, before, changes)
    db.flush()
    db.refresh(e)
    return expense_out(e, photos.photos_for(db, "expense", [e.id])[e.id])


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    e = _expense(db, expense_id)
    e.deleted_at = datetime.now(UTC)
    audit.record(
        db,
        user=user,
        action="expense.deleted",
        entity_type="expense",
        entity_id=e.id,
        details={"amount_cents": e.amount_cents},
    )
