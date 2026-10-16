"""Digital inspections: start from a work order, check items, share the report."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import require_user
from app.core.errors import Conflict
from app.db import get_db
from app.documents.render import render_pdf
from app.documents.snapshot import snapshot_inspection
from app.models import Inspection, User, WorkOrder
from app.routers.public import pdf_response
from app.schemas.common import ShortText, _strip
from app.services import documents, inspections, notify, workflow
from app.services.serialize import estimate_out

router = APIRouter(tags=["inspections"])

ItemStatus = Literal["good", "monitor", "attention", "urgent"]


@router.post("/work-orders/{wo_id}/inspection", status_code=201)
def start_inspection(wo_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Start the work order's inspection (or return the one already started)."""
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    return inspections.inspection_out(db, inspections.start(db, user, wo))


@router.get("/inspections/{inspection_id}")
def get_inspection(
    inspection_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    return inspections.inspection_out(db, inspections.get(db, inspection_id))


@router.get("/vehicles/{vehicle_id}/inspections")
def vehicle_inspections(
    vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    rows = db.scalars(
        select(Inspection)
        .where(Inspection.vehicle_id == vehicle_id)
        .order_by(Inspection.created_at.desc())
    )
    out = []
    for insp in rows:
        counts = {
            "red": sum(1 for i in insp.items if i.status in ("attention", "urgent")),
            "yellow": sum(1 for i in insp.items if i.status == "monitor"),
            "green": sum(1 for i in insp.items if i.status == "good"),
        }
        out.append(
            {
                "id": insp.id,
                "number": insp.number,
                "status": insp.status,
                "mileage": insp.mileage,
                "created_at": insp.created_at,
                "completed_at": insp.completed_at,
                "counts": counts,
            }
        )
    return out


class InspectionUpdate(BaseModel):
    summary: ShortText(5000) = None
    internal_notes: ShortText(5000) = None
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    status: Literal["in_progress", "completed"] | None = None


@router.patch("/inspections/{inspection_id}")
def update_inspection(
    inspection_id: int,
    data: InspectionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    insp = inspections.get(db, inspection_id, lock=True)
    inspections.update(db, user, insp, data.model_dump(exclude_unset=True))
    return inspections.inspection_out(db, insp)


class ItemIn(BaseModel):
    category: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=40)] = "Other"
    name: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=120)]


@router.post("/inspections/{inspection_id}/items", status_code=201)
def add_item(
    inspection_id: int,
    data: ItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    insp = inspections.get(db, inspection_id, lock=True)
    inspections.add_item(db, user, insp, data.category, data.name)
    return inspections.inspection_out(db, insp)


class ItemUpdate(BaseModel):
    name: Annotated[str | None, BeforeValidator(_strip), Field(min_length=1, max_length=120)] = None
    status: ItemStatus | None = None
    notes: ShortText(2000) = None
    recommendation: ShortText(300) = None
    estimated_cost_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None


@router.patch("/inspection-items/{item_id}")
def update_item(
    item_id: int,
    data: ItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    item = inspections.get_item(db, item_id)
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and not fields["name"]:
        fields.pop("name")
    inspections.update_item(db, user, item, fields)
    db.flush()
    return inspections.inspection_out(db, inspections.get(db, item.inspection_id))


@router.delete("/inspection-items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    item = inspections.get_item(db, item_id)
    inspection_id = item.inspection_id
    inspections.remove_item(db, user, item)
    return inspections.inspection_out(db, inspections.get(db, inspection_id))


@router.post("/inspections/{inspection_id}/estimate", status_code=201)
def estimate_from_findings(
    inspection_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    insp = inspections.get(db, inspection_id, lock=True)
    est = inspections.estimate_from_findings(db, user, insp)
    return estimate_out(est, db)


@router.get("/inspections/{inspection_id}/pdf")
def inspection_pdf(
    inspection_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    insp = inspections.get(db, inspection_id)
    return pdf_response(render_pdf(snapshot_inspection(db, insp, 0)), f"{insp.number}.pdf")


class SendIn(BaseModel):
    email: bool = True


@router.post("/inspections/{inspection_id}/send")
def send_inspection(
    inspection_id: int,
    data: SendIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Issue the report as a fixed version, make the customer's link, and email it. The
    customer can review it, ask a question, and sign to acknowledge it."""
    insp = inspections.get(db, inspection_id, lock=True)
    if insp.status != "completed":
        raise Conflict("Finish the inspection before sending the report.")
    version = documents.issue_version(db, user, insp)
    url = documents.create_link(
        db,
        user,
        purpose="inspection",
        entity=insp,
        version=version,
        days=get_settings().estimate_link_days,
    )
    db.commit()
    email = None
    if data.email:
        c = insp.customer
        email = notify.send_templated(
            db,
            "inspection_ready",
            c.email,
            {
                "customer_first_name": c.first_name,
                "customer_name": c.full_name,
                "vehicle": insp.vehicle.display_name,
                "document_number": insp.number,
                "link": url,
            },
            entity_type="inspection",
            entity_id=insp.id,
        ).as_dict()
    return {"link": url, "email": email, "version": version.version}
