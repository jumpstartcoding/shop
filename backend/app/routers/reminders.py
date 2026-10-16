"""Maintenance reminders: set them on a vehicle, see what's due, email the customer."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, BeforeValidator, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import require_user
from app.core.errors import NotFound
from app.db import get_db
from app.models import Customer, MaintenanceReminder, User, Vehicle, WorkOrder
from app.models.admin import REMINDER_KINDS
from app.schemas.common import ShortText, _strip
from app.services import reminders, workflow
from app.services.business import get_business, shop_today

router = APIRouter(tags=["maintenance reminders"])

Kind = Literal[REMINDER_KINDS]  # type: ignore[valid-type]
Mileage = Annotated[int, Field(ge=0, le=5_000_000)]


class ReminderIn(BaseModel):
    kind: Kind = "custom"
    title: Annotated[str | None, BeforeValidator(_strip), Field(max_length=120)] = None
    due_date: date | None = None
    due_mileage: Mileage | None = None
    notes: ShortText(2000) = None
    work_order_id: int | None = None

    @model_validator(mode="after")
    def has_due(self):
        if self.due_date is None and self.due_mileage is None:
            raise ValueError("Give a due date, a due mileage, or both.")
        return self


class ReminderUpdate(BaseModel):
    title: Annotated[str | None, BeforeValidator(_strip), Field(min_length=1, max_length=120)] = (
        None
    )
    due_date: date | None = None
    due_mileage: Mileage | None = None
    notes: ShortText(2000) = None
    status: Literal["open", "done", "dismissed"] | None = None


def _out(db: Session, rem: MaintenanceReminder) -> dict:
    b = get_business(db)
    return reminders.reminder_out(
        rem,
        db.get(Vehicle, rem.vehicle_id),
        db.get(Customer, rem.customer_id),
        shop_today(b),
        b.reminder_lead_days,
    )


def _get(db: Session, reminder_id: int) -> MaintenanceReminder:
    rem = db.get(MaintenanceReminder, reminder_id)
    if rem is None:
        raise NotFound("Reminder not found.")
    return rem


@router.get("/reminders/presets")
def presets(_: User = Depends(require_user)):
    return [
        {"kind": k, "title": t, "months": m, "miles": mi}
        for k, (t, m, mi) in reminders.PRESETS.items()
    ]


@router.get("/reminders")
def list_reminders(
    scope: Literal["due", "open", "closed"] = "due",
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    b = get_business(db)
    today = shop_today(b)
    if scope == "due":
        rows = reminders.due_list(db)
    else:
        statuses = ("open",) if scope == "open" else ("done", "dismissed")
        rows = db.execute(
            select(MaintenanceReminder, Vehicle, Customer)
            .join(Vehicle, Vehicle.id == MaintenanceReminder.vehicle_id)
            .join(Customer, Customer.id == MaintenanceReminder.customer_id)
            .where(MaintenanceReminder.status.in_(statuses))
            .order_by(MaintenanceReminder.due_date.asc().nulls_last(), MaintenanceReminder.id)
            .limit(500)
        ).all()
    return [reminders.reminder_out(r, v, c, today, b.reminder_lead_days) for r, v, c in rows]


@router.get("/vehicles/{vehicle_id}/reminders")
def vehicle_reminders(
    vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    v = workflow.get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    rows = db.scalars(
        select(MaintenanceReminder)
        .where(MaintenanceReminder.vehicle_id == v.id)
        .order_by(
            MaintenanceReminder.status != "open", MaintenanceReminder.due_date.asc().nulls_last()
        )
    )
    return [_out(db, r) for r in rows]


@router.post("/vehicles/{vehicle_id}/reminders", status_code=201)
def create_reminder(
    vehicle_id: int,
    data: ReminderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    v = workflow.get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    if data.work_order_id is not None:
        wo = db.get(WorkOrder, data.work_order_id)
        if wo is None or wo.vehicle_id != v.id:
            raise workflow.InvalidReference("That work order is for a different vehicle.")
    rem = MaintenanceReminder(
        vehicle_id=v.id,
        customer_id=v.customer_id,
        kind=data.kind,
        title=data.title or reminders.PRESETS[data.kind][0],
        due_date=data.due_date,
        due_mileage=data.due_mileage,
        notes=data.notes,
        work_order_id=data.work_order_id,
        status="open",
    )
    db.add(rem)
    db.flush()
    audit.record(
        db,
        user=user,
        action="reminder.created",
        entity_type="vehicle",
        entity_id=v.id,
        details={"reminder_id": rem.id, "title": rem.title},
    )
    return _out(db, rem)


@router.patch("/reminders/{reminder_id}")
def update_reminder(
    reminder_id: int,
    data: ReminderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    rem = _get(db, reminder_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("title", "") is None:
        changes.pop("title")
    status = changes.pop("status", None)
    for k, v in changes.items():
        setattr(rem, k, v)
    if rem.due_date is None and rem.due_mileage is None:
        raise workflow.InvalidReference("Give a due date, a due mileage, or both.")
    if status and status != rem.status:
        rem.status = status
        rem.closed_at = None if status == "open" else datetime.now(UTC)
        if status == "open":
            rem.emailed_at = None  # a reopened reminder can be emailed again
        audit.record(
            db,
            user=user,
            action=f"reminder.{status}",
            entity_type="vehicle",
            entity_id=rem.vehicle_id,
            details={"reminder_id": rem.id},
        )
    db.flush()
    return _out(db, rem)


@router.post("/reminders/{reminder_id}/send")
def send_reminder(
    reminder_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    rem = _get(db, reminder_id)
    result = reminders.send(db, user, rem)
    db.flush()
    return {"email": result.as_dict(), "reminder": _out(db, rem)}
