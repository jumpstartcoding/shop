"""Vehicle service history (automatic from completed work orders, plus manual records)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy.orm import Session

from app.core.deps import require_user
from app.core.errors import NotFound
from app.db import get_db
from app.models import ServiceRecord, User, Vehicle
from app.schemas.common import ShortText, _strip
from app.services import documents, history, notify, workflow

router = APIRouter(tags=["service history"])


class ShareIn(BaseModel):
    email: bool = True


@router.post("/vehicles/{vehicle_id}/share-history")
def share_history(
    vehicle_id: int,
    data: ShareIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """A private link (good for a year) where the customer sees this vehicle's service
    history, warranties, upcoming appointments and reminders, and invoices."""
    v = workflow.get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    url = documents.create_link(db, user, purpose="history", entity=v, version=None, days=365)
    db.commit()
    email = None
    if data.email:
        c = v.customer
        email = notify.send_templated(
            db,
            "service_history",
            c.email,
            {
                "customer_first_name": c.first_name,
                "customer_name": c.full_name,
                "vehicle": v.display_name,
                "link": url,
            },
            entity_type="vehicle",
            entity_id=v.id,
        ).as_dict()
    return {"link": url, "email": email}


@router.get("/vehicles/{vehicle_id}/service-history")
def service_history(
    vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    """Every completed job and manual record for the vehicle, newest first, plus the
    warranties those jobs carry (active first)."""
    v = workflow.get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    return history.vehicle_history(db, v)


class ManualRecordIn(BaseModel):
    service_date: date
    summary: Annotated[str, BeforeValidator(_strip), Field(min_length=2, max_length=500)]
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    notes: ShortText(2000) = None
    performed_by: ShortText(120) = None
    total_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None


class ManualRecordUpdate(BaseModel):
    service_date: date | None = None
    summary: Annotated[str | None, BeforeValidator(_strip), Field(min_length=2, max_length=500)] = (
        None
    )
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    notes: ShortText(2000) = None
    performed_by: ShortText(120) = None
    total_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None


def _record(db: Session, record_id: int) -> ServiceRecord:
    rec = db.get(ServiceRecord, record_id)
    if rec is None or rec.deleted_at is not None:
        raise NotFound("Service record not found.")
    return rec


@router.post("/vehicles/{vehicle_id}/service-records", status_code=201)
def add_record(
    vehicle_id: int,
    data: ManualRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Add past work by hand (done before using the app, or at another shop)."""
    v = workflow.get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    history.add_manual(db, user, v, data.model_dump())
    return history.vehicle_history(db, v)


@router.patch("/service-records/{record_id}")
def update_record(
    record_id: int,
    data: ManualRecordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    rec = _record(db, record_id)
    fields = data.model_dump(exclude_unset=True)
    for required in ("service_date", "summary"):
        if required in fields and fields[required] is None:
            fields.pop(required)
    history.update_manual(db, user, rec, fields)
    return history.vehicle_history(db, db.get(Vehicle, rec.vehicle_id))


@router.delete("/service-records/{record_id}")
def delete_record(
    record_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    rec = _record(db, record_id)
    history.remove_manual(db, user, rec)
    return history.vehicle_history(db, db.get(Vehicle, rec.vehicle_id))
