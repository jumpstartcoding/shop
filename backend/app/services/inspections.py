"""Digital vehicle inspections on a work order."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound
from app.core.numbering import next_number
from app.models import (
    Estimate,
    EstimateItem,
    Inspection,
    InspectionItem,
    User,
    WorkOrder,
)
from app.models.inspections import DEFAULT_ITEMS
from app.schemas.documents import EstimateCreate, LineItemIn
from app.services import documents, workflow
from app.services.business import get_business, shop_today
from app.services.photos import hide_photo, photo_out, photos_for

STATUS_LABEL = {
    "good": "Good",
    "monitor": "Monitor",
    "attention": "Needs attention",
    "urgent": "Urgent",
}
SUPPLEMENT_STAGES = {"approved", "in_repair", "quality_check", "ready_for_pickup"}


def start(db: Session, user: User, wo: WorkOrder) -> Inspection:
    """The work order's inspection, created with the standard checklist the first time."""
    existing = db.scalar(select(Inspection).where(Inspection.work_order_id == wo.id))
    if existing:
        return existing
    workflow.ensure_work_order_editable(wo)
    business = get_business(db)
    insp = Inspection(
        number=next_number(db, "inspection", "INS", shop_today(business).year),
        work_order_id=wo.id,
        customer_id=wo.customer_id,
        vehicle_id=wo.vehicle_id,
        status="in_progress",
        mileage=wo.mileage_in,
    )
    for i, (category, name) in enumerate(DEFAULT_ITEMS):
        insp.items.append(InspectionItem(position=i, category=category, name=name))
    db.add(insp)
    db.flush()
    audit.record(
        db,
        user=user,
        action="inspection.started",
        entity_type="inspection",
        entity_id=insp.id,
        details={"number": insp.number, "work_order": wo.number},
    )
    return insp


def ensure_editable(insp: Inspection) -> None:
    """A finished inspection is what the customer is shown; reopen it to change it."""
    if insp.status == "completed":
        raise Conflict(
            f"Inspection {insp.number} is finished. Reopen it to make changes.",
            code="inspection_finished",
        )


def get(db: Session, inspection_id: int, *, lock: bool = False) -> Inspection:
    return workflow.get_or_404(db, Inspection, inspection_id, "Inspection", lock=lock)


def get_item(db: Session, item_id: int) -> InspectionItem:
    item = db.get(InspectionItem, item_id)
    if item is None:
        raise NotFound("Inspection item not found.")
    return item


def update(db: Session, user: User, insp: Inspection, fields: dict) -> None:
    status = fields.pop("status", None)
    for k, v in fields.items():
        setattr(insp, k, v)
    if status == "completed" and insp.status != "completed":
        unchecked = [i.name for i in insp.items if not i.status]
        if unchecked:
            raise Conflict(
                f"{len(unchecked)} item(s) aren't checked yet: "
                + ", ".join(unchecked[:5])
                + (", ..." if len(unchecked) > 5 else "")
                + ". Check them or remove the ones that don't apply.",
                code="inspection_incomplete",
            )
        insp.status = "completed"
        insp.completed_at = datetime.now(UTC)
    elif status == "in_progress" and insp.status != "in_progress":
        insp.status = "in_progress"
        insp.completed_at = None
    if status or fields:
        audit.record(
            db,
            user=user,
            action="inspection.updated",
            entity_type="inspection",
            entity_id=insp.id,
            details={"fields": sorted(fields), **({"status": status} if status else {})},
        )


def add_item(db: Session, user: User, insp: Inspection, category: str, name: str) -> None:
    ensure_editable(insp)
    position = max((i.position for i in insp.items), default=-1) + 1
    insp.items.append(InspectionItem(position=position, category=category, name=name))
    db.flush()


def update_item(db: Session, user: User, item: InspectionItem, fields: dict) -> None:
    ensure_editable(item.inspection)
    for k, v in fields.items():
        setattr(item, k, v)
    if "status" in fields:
        audit.record(
            db,
            user=user,
            action="inspection.item_status",
            entity_type="inspection",
            entity_id=item.inspection_id,
            details={"item": item.name, "status": fields["status"]},
        )


def remove_item(db: Session, user: User, item: InspectionItem) -> None:
    ensure_editable(item.inspection)
    for p in photos_for(db, "inspection_item", [item.id])[item.id]:
        hide_photo(db, user, p)
    insp = db.get(Inspection, item.inspection_id)
    insp.items.remove(item)
    db.flush()


def estimate_from_findings(db: Session, user: User, insp: Inspection) -> Estimate:
    """Draft estimate for the red and yellow items that have a recommended repair or a cost,
    with the inspection attached so the customer sees the findings and photos with it.

    On a work order still being diagnosed, the estimate starts from the work order's own
    lines (so approving it doesn't drop them). Once work is already approved, it's an
    additional-work request whose lines are added to the job on approval.
    """
    findings = [
        i
        for i in insp.items
        if i.status in ("urgent", "attention", "monitor")
        and (i.recommendation or i.estimated_cost_cents)
    ]
    if not findings:
        raise Conflict(
            "No findings have a recommended repair or estimated cost yet. Add them to the "
            "red or yellow items first."
        )
    wo = db.get(WorkOrder, insp.work_order_id)
    business = get_business(db)
    supplement = wo.status in SUPPLEMENT_STAGES
    est = workflow.create_estimate(
        db,
        user,
        EstimateCreate(
            customer_id=insp.customer_id,
            vehicle_id=insp.vehicle_id,
            work_order_id=wo.id,
            mileage=insp.mileage,
            customer_notes=insp.summary,
            items=[] if supplement else None,
            is_supplement=supplement,
        ),
    )
    order = {"urgent": 0, "attention": 1, "monitor": 2}
    for item in sorted(findings, key=lambda i: (order[i.status], i.position)):
        workflow.append_line(
            est,
            EstimateItem,
            LineItemIn(
                kind="labor",
                description=(item.recommendation or item.name)[:300],
                quantity="1",
                unit_price_cents=item.estimated_cost_cents or 0,
            ),
            business,
        )
    est.inspection_id = insp.id
    db.flush()
    audit.record(
        db,
        user=user,
        action="inspection.estimate_created",
        entity_type="inspection",
        entity_id=insp.id,
        details={"estimate": est.number, "findings": len(findings)},
    )
    return est


def inspection_out(db: Session, insp: Inspection) -> dict:
    wo = db.get(WorkOrder, insp.work_order_id)
    photos = photos_for(db, "inspection_item", [i.id for i in insp.items])
    items = [
        {
            "id": i.id,
            "position": i.position,
            "category": i.category,
            "name": i.name,
            "status": i.status,
            "notes": i.notes,
            "recommendation": i.recommendation,
            "estimated_cost_cents": i.estimated_cost_cents,
            "photos": [photo_out(p) for p in photos[i.id]],
        }
        for i in insp.items
    ]
    counts = {s: sum(1 for i in insp.items if i.status == s) for s in STATUS_LABEL}
    counts["unchecked"] = sum(1 for i in insp.items if not i.status)
    return {
        "id": insp.id,
        "number": insp.number,
        "status": insp.status,
        "work_order_id": insp.work_order_id,
        "work_order_number": wo.number,
        "work_order_status": wo.status,
        "customer_id": insp.customer_id,
        "customer_name": insp.customer.full_name,
        "customer_email": insp.customer.email,
        "customer_phone": insp.customer.phone,
        "vehicle_id": insp.vehicle_id,
        "vehicle_name": insp.vehicle.display_name,
        "mileage": insp.mileage,
        "summary": insp.summary,
        "internal_notes": insp.internal_notes,
        "completed_at": insp.completed_at,
        "created_at": insp.created_at,
        "updated_at": insp.updated_at,
        "items": items,
        "counts": counts,
        "estimate_ids": list(
            db.scalars(
                select(Estimate.id).where(Estimate.inspection_id == insp.id).order_by(Estimate.id)
            )
        ),
        "authorization": documents.authorization_state(db, "inspection", insp),
    }
