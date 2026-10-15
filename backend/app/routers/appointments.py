from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import require_user
from app.core.errors import AppError
from app.db import get_db
from app.models import Appointment, Customer, User, Vehicle, WorkOrder
from app.schemas.customers import (
    AppointmentCreate,
    AppointmentOut,
    AppointmentStatus,
    AppointmentUpdate,
)
from app.services.workflow import get_or_404

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _out(a: Appointment) -> AppointmentOut:
    out = AppointmentOut.model_validate(a)
    out.customer_name = a.customer.full_name if a.customer else a.contact_name
    out.vehicle_name = a.vehicle.display_name if a.vehicle else a.vehicle_description
    return out


def _check_refs(db: Session, a: Appointment) -> None:
    if a.customer_id is not None:
        c = db.get(Customer, a.customer_id)
        if c is None:
            raise AppError("Customer not found.", status_code=422, code="invalid_reference")
    if a.vehicle_id is not None:
        v = db.get(Vehicle, a.vehicle_id)
        if v is None or (a.customer_id is not None and v.customer_id != a.customer_id):
            raise AppError(
                "That vehicle doesn't belong to this customer.",
                status_code=422,
                code="invalid_reference",
            )
    if a.work_order_id is not None:
        wo = db.get(WorkOrder, a.work_order_id)
        if wo is None or (a.customer_id is not None and wo.customer_id != a.customer_id):
            raise AppError(
                "That work order is for a different customer.",
                status_code=422,
                code="invalid_reference",
            )
    if a.status in ("confirmed", "checked_in", "in_progress") and a.starts_at is None:
        raise AppError(
            "Pick a date and time before confirming the appointment.",
            status_code=422,
            code="validation_error",
        )


@router.get("", response_model=list[AppointmentOut])
def list_appointments(
    start: datetime | None = Query(
        None, alias="from", description="Range start (ISO, with offset)"
    ),
    end: datetime | None = Query(None, alias="to"),
    status: list[AppointmentStatus] | None = Query(None),
    customer_id: int | None = None,
    include_unscheduled: bool = Query(True, description="Include requests with no time set yet"),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    """Calendar feed. A day/week/month view passes its visible range."""
    stmt = select(Appointment)
    if start is not None or end is not None:
        in_range = Appointment.starts_at.is_not(None)
        if start is not None:
            in_range = in_range & (Appointment.starts_at >= start)
        if end is not None:
            in_range = in_range & (Appointment.starts_at < end)
        stmt = stmt.where(
            or_(in_range, Appointment.starts_at.is_(None)) if include_unscheduled else in_range
        )
    if status:
        stmt = stmt.where(Appointment.status.in_(status))
    if customer_id is not None:
        stmt = stmt.where(Appointment.customer_id == customer_id)
    rows = db.scalars(
        stmt.order_by(Appointment.starts_at.asc().nulls_first(), Appointment.id).limit(500)
    )
    return [_out(a) for a in rows]


@router.post("", response_model=AppointmentOut, status_code=201)
def create_appointment(
    data: AppointmentCreate, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    appt = Appointment(**data.model_dump(), source="admin")
    _check_refs(db, appt)
    db.add(appt)
    db.flush()
    audit.record(
        db,
        user=user,
        action="appointment.created",
        entity_type="appointment",
        entity_id=appt.id,
        details={"starts_at": appt.starts_at, "status": appt.status},
    )
    return _out(appt)


@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(
    appointment_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    return _out(get_or_404(db, Appointment, appointment_id, "Appointment"))


@router.patch("/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Reschedule (drag on the calendar), change status, or edit details."""
    appt = get_or_404(db, Appointment, appointment_id, "Appointment")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("status") is None:
        changes.pop("status", None)
    before = {k: getattr(appt, k) for k in changes}
    for k, v in changes.items():
        setattr(appt, k, v)
    if appt.starts_at and appt.ends_at and appt.ends_at <= appt.starts_at:
        raise AppError(
            "End time must be after start time.", status_code=422, code="validation_error"
        )
    _check_refs(db, appt)
    delta = audit.diff(before, changes)
    if delta:
        action = "appointment.rescheduled" if "starts_at" in delta else "appointment.updated"
        audit.record(
            db,
            user=user,
            action=action,
            entity_type="appointment",
            entity_id=appt.id,
            details=delta,
        )
    db.flush()
    return _out(appt)
