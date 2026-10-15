from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import require_user
from app.db import get_db
from app.models import Customer, Estimate, EstimateItem, User
from app.schemas.common import Page
from app.schemas.documents import (
    DecisionIn,
    DocumentListItem,
    EstimateCreate,
    EstimateOut,
    EstimateUpdate,
    LineItemIn,
    WorkOrderOut,
)
from app.services import workflow
from app.services.business import get_business
from app.services.serialize import estimate_out, work_order_out

router = APIRouter(prefix="/estimates", tags=["estimates"])


@router.get("", response_model=Page[DocumentListItem])
def list_estimates(
    status: list[str] | None = Query(None),
    customer_id: int | None = None,
    vehicle_id: int | None = None,
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(Estimate)
    if status:
        stmt = stmt.where(Estimate.status.in_(status))
    if customer_id is not None:
        stmt = stmt.where(Estimate.customer_id == customer_id)
    if vehicle_id is not None:
        stmt = stmt.where(Estimate.vehicle_id == vehicle_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.join(Customer, Customer.id == Estimate.customer_id).where(
            or_(
                func.lower(Estimate.number).like(like),
                func.lower(Customer.first_name + " " + Customer.last_name).like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Estimate.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        DocumentListItem(
            id=e.id,
            number=e.number,
            status=e.status,
            customer_name=e.customer.full_name,
            vehicle_name=e.vehicle.display_name,
            total_cents=e.total_cents,
            date=e.created_at.date(),
        )
        for e in rows
    ]
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


@router.post("", response_model=EstimateOut, status_code=201)
def create_estimate(
    data: EstimateCreate, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    return estimate_out(workflow.create_estimate(db, user, data))


@router.get("/{est_id}", response_model=EstimateOut)
def get_estimate(est_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    return estimate_out(workflow.get_or_404(db, Estimate, est_id, "Estimate"))


@router.patch("/{est_id}", response_model=EstimateOut)
def update_estimate(
    est_id: int,
    data: EstimateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    changes = data.model_dump(exclude_unset=True)
    # Internal notes can always be edited; anything the customer sees is locked once sent.
    if set(changes) - {"internal_notes"}:
        workflow.ensure_estimate_editable(est)
    before = {k: getattr(est, k) for k in changes}
    for k, v in changes.items():
        setattr(est, k, v)
    delta = audit.diff(before, changes)
    if delta:
        if "internal_notes" in delta:
            delta["internal_notes"] = {"changed": True}
        audit.record(
            db,
            user=user,
            action="estimate.updated",
            entity_type="estimate",
            entity_id=est.id,
            details=delta,
        )
    db.flush()
    return estimate_out(est)


@router.put("/{est_id}/items", response_model=EstimateOut)
def replace_items(
    est_id: int,
    items: list[LineItemIn],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    workflow.ensure_estimate_editable(est)
    workflow.replace_lines(est, EstimateItem, items, get_business(db))
    db.flush()
    audit.record(
        db,
        user=user,
        action="estimate.lines_updated",
        entity_type="estimate",
        entity_id=est.id,
        details={"line_count": len(items), "total_cents": est.total_cents},
    )
    return estimate_out(est)


@router.post("/{est_id}/items", response_model=EstimateOut, status_code=201)
def add_item(
    est_id: int, item: LineItemIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    workflow.ensure_estimate_editable(est)
    line = workflow.append_line(est, EstimateItem, item, get_business(db))
    db.flush()
    audit.record(
        db,
        user=user,
        action="estimate.line_added",
        entity_type="estimate",
        entity_id=est.id,
        details={"description": line.description, "total_cents": est.total_cents},
    )
    return estimate_out(est)


@router.delete("/{est_id}/items/{item_id}", response_model=EstimateOut)
def delete_item(
    est_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    workflow.ensure_estimate_editable(est)
    workflow.remove_line(est, item_id)
    db.flush()
    audit.record(
        db,
        user=user,
        action="estimate.line_removed",
        entity_type="estimate",
        entity_id=est.id,
        details={"item_id": item_id, "total_cents": est.total_cents},
    )
    return estimate_out(est)


@router.post("/{est_id}/mark-sent", response_model=EstimateOut)
def mark_sent(est_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Record that the estimate was given to the customer (printed, shown, or sent outside
    the app). Locks it against edits. Emailing from the app arrives in Phase 2."""
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    workflow.mark_estimate_sent(db, user, est)
    return estimate_out(est)


@router.post("/{est_id}/decision", response_model=EstimateOut)
def record_decision(
    est_id: int, data: DecisionIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Record an approval or decline the customer gave in person, by phone, email, or text."""
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    workflow.record_estimate_decision(db, user, est, data)
    return estimate_out(est)


@router.post("/{est_id}/revise", response_model=EstimateOut)
def revise(est_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Unlock as a new version. The previous version's status and total stay in the audit log,
    and any earlier approval no longer applies."""
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    workflow.revise_estimate(db, user, est)
    return estimate_out(est)


@router.post("/{est_id}/convert", response_model=WorkOrderOut, status_code=201)
def convert(est_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    wo = workflow.convert_estimate(db, user, est)
    db.flush()
    return work_order_out(db, wo)
