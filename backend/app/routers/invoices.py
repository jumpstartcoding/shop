from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import require_user
from app.db import get_db
from app.models import Customer, Invoice, InvoiceItem, Payment, User
from app.schemas.common import Page
from app.schemas.documents import (
    DocumentListItem,
    InvoiceCreate,
    InvoiceOut,
    InvoiceUpdate,
    LineItemIn,
    PaymentIn,
    PaymentOut,
    VoidIn,
)
from app.services import workflow
from app.services.business import get_business, shop_today
from app.services.serialize import invoice_out

router = APIRouter(tags=["invoices & payments"])

UNPAID = ("sent", "viewed", "partially_paid", "overdue")


@router.get("/invoices", response_model=Page[DocumentListItem])
def list_invoices(
    status: list[str] | None = Query(None),
    unpaid_only: bool = False,
    customer_id: int | None = None,
    vehicle_id: int | None = None,
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(Invoice)
    if status:
        stmt = stmt.where(Invoice.status.in_(status))
    if unpaid_only:
        stmt = stmt.where(Invoice.status.in_(UNPAID))
    if customer_id is not None:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if vehicle_id is not None:
        stmt = stmt.where(Invoice.vehicle_id == vehicle_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.join(Customer, Customer.id == Invoice.customer_id).where(
            or_(
                func.lower(Invoice.number).like(like),
                func.lower(Customer.first_name + " " + Customer.last_name).like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Invoice.issue_date.desc(), Invoice.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        DocumentListItem(
            id=i.id,
            number=i.number,
            status=i.status,
            customer_name=i.customer.full_name,
            vehicle_name=i.vehicle.display_name,
            total_cents=i.total_cents,
            balance_cents=i.balance_cents,
            date=i.issue_date,
        )
        for i in rows
    ]
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(
    data: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """A standalone invoice (counter sale, quick job). Most invoices come from a work order
    via POST /work-orders/{id}/invoice."""
    inv = workflow.create_invoice(db, user, data)
    db.refresh(inv)
    return invoice_out(inv)


def _load(db: Session, inv_id: int, lock: bool = False) -> Invoice:
    inv = workflow.get_or_404(db, Invoice, inv_id, "Invoice", lock=lock)
    # Overdue is time-based; bring the stored status up to date when anyone looks.
    before = inv.status
    workflow.settle_invoice_status(inv, shop_today(get_business(db)))
    if before != inv.status:
        db.flush()
    return inv


@router.get("/invoices/{inv_id}", response_model=InvoiceOut)
def get_invoice(inv_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    return invoice_out(_load(db, inv_id))


@router.patch("/invoices/{inv_id}", response_model=InvoiceOut)
def update_invoice(
    inv_id: int,
    data: InvoiceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    inv = _load(db, inv_id, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if inv.status == "void":
        workflow.ensure_invoice_editable(inv)
    if set(changes) & {"issue_date", "mileage"}:
        workflow.ensure_invoice_editable(inv)
    before = {k: getattr(inv, k) for k in changes}
    for k, v in changes.items():
        setattr(inv, k, v)
    if inv.due_date and inv.due_date < inv.issue_date:
        from app.core.errors import AppError

        raise AppError(
            "The due date can't be before the invoice date.",
            status_code=422,
            code="validation_error",
        )
    workflow.settle_invoice_status(inv, shop_today(get_business(db)))
    delta = audit.diff(before, changes)
    if delta:
        if "internal_notes" in delta:
            delta["internal_notes"] = {"changed": True}
        audit.record(
            db,
            user=user,
            action="invoice.updated",
            entity_type="invoice",
            entity_id=inv.id,
            details=delta,
        )
    db.flush()
    return invoice_out(inv)


@router.put("/invoices/{inv_id}/items", response_model=InvoiceOut)
def replace_items(
    inv_id: int,
    items: list[LineItemIn],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    inv = _load(db, inv_id, lock=True)
    workflow.ensure_invoice_editable(inv)
    before_total = inv.total_cents
    workflow.replace_lines(inv, InvoiceItem, items, get_business(db))
    db.flush()
    audit.record(
        db,
        user=user,
        action="invoice.lines_updated",
        entity_type="invoice",
        entity_id=inv.id,
        details={"total_cents": {"from": before_total, "to": inv.total_cents}},
    )
    return invoice_out(inv)


@router.post("/invoices/{inv_id}/items", response_model=InvoiceOut, status_code=201)
def add_item(
    inv_id: int, item: LineItemIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    inv = _load(db, inv_id, lock=True)
    workflow.ensure_invoice_editable(inv)
    line = workflow.append_line(inv, InvoiceItem, item, get_business(db))
    db.flush()
    audit.record(
        db,
        user=user,
        action="invoice.line_added",
        entity_type="invoice",
        entity_id=inv.id,
        details={"description": line.description, "total_cents": inv.total_cents},
    )
    return invoice_out(inv)


@router.delete("/invoices/{inv_id}/items/{item_id}", response_model=InvoiceOut)
def delete_item(
    inv_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    inv = _load(db, inv_id, lock=True)
    workflow.ensure_invoice_editable(inv)
    workflow.remove_line(inv, item_id)
    db.flush()
    audit.record(
        db,
        user=user,
        action="invoice.line_removed",
        entity_type="invoice",
        entity_id=inv.id,
        details={"item_id": item_id, "total_cents": inv.total_cents},
    )
    return invoice_out(inv)


@router.post("/invoices/{inv_id}/mark-sent", response_model=InvoiceOut)
def mark_sent(inv_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Record that the invoice was handed or sent to the customer outside the app.
    Emailing from the app arrives in Phase 2."""
    inv = _load(db, inv_id, lock=True)
    workflow.mark_invoice_sent(db, user, inv)
    return invoice_out(inv)


@router.post("/invoices/{inv_id}/void", response_model=InvoiceOut)
def void(
    inv_id: int, data: VoidIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    inv = _load(db, inv_id, lock=True)
    workflow.void_invoice(db, user, inv, data.reason)
    return invoice_out(inv)


@router.post("/invoices/{inv_id}/payments", response_model=InvoiceOut, status_code=201)
def record_payment(
    inv_id: int, data: PaymentIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Record cash, check, card-terminal, or other payment. Online payments are recorded
    by the Stripe webhook (Phase 3)."""
    workflow.record_manual_payment(db, user, inv_id, data)
    db.flush()
    inv = workflow.get_or_404(db, Invoice, inv_id, "Invoice")
    db.refresh(inv)
    return invoice_out(inv)


@router.get("/payments", response_model=Page[PaymentOut])
def list_payments(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    method: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(Payment, Invoice.number).join(Invoice, Invoice.id == Payment.invoice_id)
    if start is not None:
        stmt = stmt.where(Payment.paid_at >= start)
    if end is not None:
        stmt = stmt.where(Payment.paid_at < end)
    if method:
        stmt = stmt.where(Payment.method == method)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(Payment.paid_at.desc(), Payment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for payment, number in rows:
        out = PaymentOut.model_validate(payment)
        out.invoice_number = number
        items.append(out)
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


@router.post("/payments/{payment_id}/void", response_model=InvoiceOut)
def void_payment(
    payment_id: int, data: VoidIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    payment = workflow.void_manual_payment(db, user, payment_id, data.reason)
    db.flush()
    inv = workflow.get_or_404(db, Invoice, payment.invoice_id, "Invoice")
    db.refresh(inv)
    return invoice_out(inv)
