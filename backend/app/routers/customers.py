from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import client_ip, require_user
from app.core.errors import Conflict
from app.db import get_db
from app.models import (
    Appointment,
    Customer,
    Estimate,
    Invoice,
    Payment,
    User,
    Vehicle,
    WorkOrder,
)
from app.schemas.common import Page, digits_only
from app.schemas.customers import (
    CustomerCreate,
    CustomerDetail,
    CustomerListItem,
    CustomerOut,
    CustomerUpdate,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)
from app.schemas.documents import DocumentListItem
from app.services.workflow import get_or_404

router = APIRouter(tags=["customers & vehicles"])

# Invoices that count toward what a customer owes (drafts haven't been issued yet).
BILLED = ("sent", "viewed", "partially_paid", "overdue")


def _balance_by_customer(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Invoice.customer_id, func.sum(Invoice.total_cents - Invoice.amount_paid_cents))
        .where(Invoice.customer_id.in_(ids), Invoice.status.in_(BILLED))
        .group_by(Invoice.customer_id)
    )
    return {cid: int(total or 0) for cid, total in rows}


def _vin_conflict(db: Session, vin: str | None, exclude_id: int | None = None) -> None:
    if not vin:
        return
    stmt = select(Vehicle).where(Vehicle.vin == vin)
    if exclude_id:
        stmt = stmt.where(Vehicle.id != exclude_id)
    other = db.scalar(stmt)
    if other:
        raise Conflict(
            f"VIN {vin} is already on file for {other.display_name} "
            f"(customer #{other.customer_id}).",
            code="duplicate_vin",
        )


# ------------------------------------------------------------------ customers


@router.get("/customers", response_model=Page[CustomerListItem])
def list_customers(
    q: str | None = Query(None, max_length=100, description="Name, phone, email, VIN or plate"),
    include_archived: bool = False,
    sort: Literal["name", "-created_at", "created_at"] = "name",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(Customer)
    if not include_archived:
        stmt = stmt.where(Customer.archived_at.is_(None))
    if q and q.strip():
        term = q.strip()
        like = f"%{term.lower()}%"
        conds = [
            func.lower(Customer.first_name + " " + Customer.last_name).like(like),
            func.lower(Customer.email).like(like),
        ]
        digits = digits_only(term)
        if digits and len(digits) >= 3:
            conds.append(Customer.phone_digits.like(f"%{digits}%"))
        vehicle_match = select(Vehicle.customer_id).where(
            or_(
                func.upper(Vehicle.vin).like(f"%{term.upper()}%"),
                func.upper(Vehicle.license_plate).like(f"%{term.upper().replace(' ', '')}%"),
                func.lower(Vehicle.make + " " + Vehicle.model).like(like),
            )
        )
        conds.append(Customer.id.in_(vehicle_match))
        stmt = stmt.where(or_(*conds))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {
        "name": (func.lower(Customer.last_name), func.lower(Customer.first_name)),
        "created_at": (Customer.created_at,),
        "-created_at": (Customer.created_at.desc(),),
    }[sort]
    customers = list(
        db.scalars(
            stmt.order_by(*order, Customer.id).offset((page - 1) * page_size).limit(page_size)
        )
    )
    ids = [c.id for c in customers]
    vcounts = (
        dict(
            db.execute(
                select(Vehicle.customer_id, func.count())
                .where(Vehicle.customer_id.in_(ids), Vehicle.archived_at.is_(None))
                .group_by(Vehicle.customer_id)
            ).all()
        )
        if ids
        else {}
    )
    balances = _balance_by_customer(db, ids)
    items = [
        CustomerListItem(
            id=c.id,
            full_name=c.full_name,
            phone=c.phone,
            email=c.email,
            vehicle_count=vcounts.get(c.id, 0),
            balance_cents=balances.get(c.id, 0),
            archived_at=c.archived_at,
        )
        for c in customers
    ]
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


@router.post("/customers", response_model=CustomerDetail, status_code=201)
def create_customer(
    data: CustomerCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Create a customer, optionally with their first vehicle in the same step."""
    fields = data.model_dump(exclude={"vehicle"})
    customer = Customer(
        **{**fields, "last_name": fields.get("last_name") or ""},
        phone_digits=digits_only(data.phone),
    )
    db.add(customer)
    db.flush()
    if data.vehicle:
        _vin_conflict(db, data.vehicle.vin)
        db.add(Vehicle(customer_id=customer.id, **data.vehicle.model_dump()))
    audit.record(
        db,
        user=user,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        ip_address=client_ip(request),
    )
    db.flush()
    db.refresh(customer)
    return _detail(db, customer)


def _detail(db: Session, customer: Customer) -> CustomerDetail:
    out = CustomerOut.model_validate(customer)
    vehicles = [VehicleOut.model_validate(v) for v in customer.vehicles if v.archived_at is None]
    paid = db.scalar(
        select(func.coalesce(func.sum(Payment.amount_cents), 0))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Invoice.customer_id == customer.id, Payment.status == "succeeded")
    )
    return CustomerDetail(
        **out.model_dump(),
        vehicles=vehicles,
        balance_cents=_balance_by_customer(db, [customer.id]).get(customer.id, 0),
        lifetime_paid_cents=int(paid or 0),
    )


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    return _detail(db, get_or_404(db, Customer, customer_id, "Customer"))


@router.patch("/customers/{customer_id}", response_model=CustomerDetail)
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    customer = get_or_404(db, Customer, customer_id, "Customer")
    changes = data.model_dump(exclude_unset=True)
    if "last_name" in changes and changes["last_name"] is None:
        changes["last_name"] = ""
    before = {k: getattr(customer, k) for k in changes}
    for k, v in changes.items():
        setattr(customer, k, v)
    if "phone" in changes:
        customer.phone_digits = digits_only(customer.phone)
    if not (customer.phone or customer.email):
        raise Conflict("Keep at least a phone number or email on file.", code="validation_error")
    delta = audit.diff(before, changes)
    if delta:
        # Internal note contents aren't copied into the audit log, only the fact they changed.
        if "internal_notes" in delta:
            delta["internal_notes"] = {"changed": True}
        audit.record(
            db,
            user=user,
            action="customer.updated",
            entity_type="customer",
            entity_id=customer.id,
            details=delta,
            ip_address=client_ip(request),
        )
    db.flush()
    return _detail(db, customer)


@router.post("/customers/{customer_id}/archive", response_model=CustomerDetail)
def archive_customer(
    customer_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    customer = get_or_404(db, Customer, customer_id, "Customer")
    if customer.archived_at is None:
        customer.archived_at = datetime.now(UTC)
        audit.record(
            db, user=user, action="customer.archived", entity_type="customer", entity_id=customer.id
        )
    return _detail(db, customer)


@router.post("/customers/{customer_id}/restore", response_model=CustomerDetail)
def restore_customer(
    customer_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    customer = get_or_404(db, Customer, customer_id, "Customer")
    if customer.archived_at is not None:
        customer.archived_at = None
        audit.record(
            db, user=user, action="customer.restored", entity_type="customer", entity_id=customer.id
        )
    return _detail(db, customer)


@router.get("/customers/{customer_id}/history")
def customer_history(
    customer_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    """Everything for one customer in one call: appointments, work orders, estimates,
    invoices, payments. Sized for a single shop's customer, so no pagination."""
    customer = get_or_404(db, Customer, customer_id, "Customer")
    return _history(db, customer_id=customer.id)


def _history(db: Session, *, customer_id: int | None = None, vehicle_id: int | None = None):
    def scope(model):
        stmt = select(model)
        if customer_id is not None:
            stmt = stmt.where(model.customer_id == customer_id)
        if vehicle_id is not None:
            stmt = stmt.where(model.vehicle_id == vehicle_id)
        return stmt

    def doc_item(d, when, balance=None):
        return DocumentListItem(
            id=d.id,
            number=d.number,
            status=d.status,
            customer_name=d.customer.full_name,
            vehicle_name=d.vehicle.display_name,
            total_cents=d.total_cents,
            balance_cents=balance,
            date=when,
        )

    work_orders = db.scalars(scope(WorkOrder).order_by(WorkOrder.created_at.desc()))
    estimates = db.scalars(scope(Estimate).order_by(Estimate.created_at.desc()))
    invoices = list(
        db.scalars(scope(Invoice).order_by(Invoice.issue_date.desc(), Invoice.id.desc()))
    )
    appointments = db.scalars(
        scope(Appointment).order_by(Appointment.starts_at.desc().nulls_last())
    )
    payments = (
        db.scalars(
            select(Payment)
            .where(Payment.invoice_id.in_([i.id for i in invoices]))
            .order_by(Payment.paid_at.desc())
        )
        if invoices
        else []
    )
    return {
        "work_orders": [doc_item(w, w.created_at.date()) for w in work_orders],
        "estimates": [doc_item(e, e.created_at.date()) for e in estimates],
        "invoices": [doc_item(i, i.issue_date, i.balance_cents) for i in invoices],
        "appointments": [
            {
                "id": a.id,
                "status": a.status,
                "starts_at": a.starts_at,
                "requested_service": a.requested_service,
                "vehicle_id": a.vehicle_id,
            }
            for a in appointments
        ],
        "payments": [
            {
                "id": p.id,
                "invoice_id": p.invoice_id,
                "amount_cents": p.amount_cents,
                "method": p.method,
                "status": p.status,
                "paid_at": p.paid_at,
            }
            for p in payments
        ],
    }


# ------------------------------------------------------------------ vehicles


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(
    data: VehicleCreate, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    customer = get_or_404(db, Customer, data.customer_id, "Customer")
    if customer.archived_at is not None:
        raise Conflict("Restore this customer before adding a vehicle.")
    _vin_conflict(db, data.vin)
    vehicle = Vehicle(**data.model_dump())
    db.add(vehicle)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent duplicate VIN
        raise Conflict("That VIN is already on file.", code="duplicate_vin") from exc
    audit.record(
        db,
        user=user,
        action="vehicle.created",
        entity_type="vehicle",
        entity_id=vehicle.id,
        details={"customer_id": customer.id},
    )
    return vehicle


@router.get("/vehicles", response_model=Page[VehicleOut])
def list_vehicles(
    q: str | None = Query(None, max_length=60),
    customer_id: int | None = None,
    include_archived: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(Vehicle)
    if customer_id is not None:
        stmt = stmt.where(Vehicle.customer_id == customer_id)
    if not include_archived:
        stmt = stmt.where(Vehicle.archived_at.is_(None))
    if q and q.strip():
        t = q.strip().upper()
        stmt = stmt.where(
            or_(
                Vehicle.vin.like(f"%{t}%"),
                func.upper(Vehicle.license_plate).like(f"%{t.replace(' ', '')}%"),
                func.upper(func.concat_ws(" ", Vehicle.year, Vehicle.make, Vehicle.model)).like(
                    f"%{t}%"
                ),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(
        stmt.order_by(Vehicle.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page(
        items=[VehicleOut.model_validate(v) for v in items],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    return get_or_404(db, Vehicle, vehicle_id, "Vehicle")


@router.get("/vehicles/{vehicle_id}/history")
def vehicle_history(
    vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    vehicle = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    return _history(db, vehicle_id=vehicle.id)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int,
    data: VehicleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("customer_id") is None:
        changes.pop("customer_id", None)
    else:
        new_owner = get_or_404(db, Customer, changes["customer_id"], "Customer")
        if new_owner.archived_at is not None:
            raise Conflict("Can't move a vehicle to an archived customer.")
    if "vin" in changes:
        _vin_conflict(db, changes["vin"], exclude_id=vehicle.id)
    before = {k: getattr(vehicle, k) for k in changes}
    for k, v in changes.items():
        setattr(vehicle, k, v)
    delta = audit.diff(before, changes)
    if delta:
        audit.record(
            db,
            user=user,
            action="vehicle.updated",
            entity_type="vehicle",
            entity_id=vehicle.id,
            details=delta,
        )
    db.flush()
    return vehicle


@router.post("/vehicles/{vehicle_id}/archive", response_model=VehicleOut)
def archive_vehicle(
    vehicle_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    vehicle = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    if vehicle.archived_at is None:
        vehicle.archived_at = datetime.now(UTC)
        audit.record(
            db, user=user, action="vehicle.archived", entity_type="vehicle", entity_id=vehicle.id
        )
    return vehicle


@router.post("/vehicles/{vehicle_id}/restore", response_model=VehicleOut)
def restore_vehicle(
    vehicle_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    vehicle = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    vehicle.archived_at = None
    audit.record(
        db, user=user, action="vehicle.restored", entity_type="vehicle", entity_id=vehicle.id
    )
    return vehicle
