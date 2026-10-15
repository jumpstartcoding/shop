from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import require_user
from app.db import get_db
from app.models import Customer, User, Vehicle, WorkOrder, WorkOrderItem
from app.models.documents import QC_CHECKLIST_KEYS, WORK_ORDER_STATUSES
from app.schemas.common import Page
from app.schemas.documents import (
    InvoiceFromWorkOrder,
    InvoiceOut,
    LineItemIn,
    StatusChange,
    WorkOrderCard,
    WorkOrderCreate,
    WorkOrderOut,
    WorkOrderStatus,
    WorkOrderUpdate,
)
from app.services import notify, workflow
from app.services.business import get_business
from app.services.serialize import invoice_out, work_order_card, work_order_out

router = APIRouter(prefix="/work-orders", tags=["work orders"])

BOARD_COLUMNS = [s for s in WORK_ORDER_STATUSES if s != "cancelled"]


@router.get("", response_model=Page[WorkOrderCard])
def list_work_orders(
    status: list[WorkOrderStatus] | None = Query(None),
    open_only: bool = False,
    customer_id: int | None = None,
    vehicle_id: int | None = None,
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(WorkOrder)
    if status:
        stmt = stmt.where(WorkOrder.status.in_(status))
    if open_only:
        stmt = stmt.where(WorkOrder.status.not_in(workflow.TERMINAL_WO))
    if customer_id is not None:
        stmt = stmt.where(WorkOrder.customer_id == customer_id)
    if vehicle_id is not None:
        stmt = stmt.where(WorkOrder.vehicle_id == vehicle_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.join(Customer, Customer.id == WorkOrder.customer_id).where(
            or_(
                func.lower(WorkOrder.number).like(like),
                func.lower(WorkOrder.concern).like(like),
                func.lower(Customer.first_name + " " + Customer.last_name).like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(WorkOrder.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page(
        items=[work_order_card(w) for w in rows], total=total or 0, page=page, page_size=page_size
    )


@router.get("/board")
def status_board(db: Session = Depends(get_db), _: User = Depends(require_user)):
    """Open work orders grouped by status, plus anything completed in the last 7 days."""
    recent = datetime.now(UTC) - timedelta(days=7)
    rows = db.scalars(
        select(WorkOrder)
        .where(
            or_(
                WorkOrder.status.not_in(workflow.TERMINAL_WO),
                (WorkOrder.status == "completed") & (WorkOrder.completed_at >= recent),
            )
        )
        .order_by(WorkOrder.promised_at.asc().nulls_last(), WorkOrder.created_at)
    )
    columns: dict[str, list[WorkOrderCard]] = {s: [] for s in BOARD_COLUMNS}
    for wo in rows:
        columns[wo.status].append(work_order_card(wo))
    return {
        "columns": [{"status": s, "work_orders": columns[s]} for s in BOARD_COLUMNS],
        "checklist_keys": list(QC_CHECKLIST_KEYS),
    }


@router.post("", response_model=WorkOrderOut, status_code=201)
def create_work_order(
    data: WorkOrderCreate, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    wo = workflow.create_work_order(db, user, data)
    return work_order_out(db, wo)


@router.get("/{wo_id}", response_model=WorkOrderOut)
def get_work_order(wo_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    return work_order_out(db, workflow.get_or_404(db, WorkOrder, wo_id, "Work order"))


@router.patch("/{wo_id}", response_model=WorkOrderOut)
def update_work_order(
    wo_id: int,
    data: WorkOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    changes = data.model_dump(exclude_unset=True)
    # Notes and the QC checklist stay editable after completion; charges and mileage don't.
    if set(changes) - {"customer_notes", "internal_notes", "qc_checklist"}:
        workflow.ensure_work_order_editable(wo)
    if "qc_checklist" in changes:
        checklist = changes["qc_checklist"] or {}
        unknown = set(checklist) - set(QC_CHECKLIST_KEYS)
        if unknown:
            from app.core.errors import AppError

            raise AppError(
                f"Unknown checklist item: {', '.join(sorted(unknown))}.",
                status_code=422,
                code="validation_error",
            )
        changes["qc_checklist"] = {**wo.qc_checklist, **checklist}
    before = {k: getattr(wo, k) for k in changes}
    for k, v in changes.items():
        setattr(wo, k, v)
    if changes.get("mileage_in") or changes.get("mileage_out"):
        vehicle = db.get(Vehicle, wo.vehicle_id)
        workflow._bump_mileage(vehicle, wo.mileage_out or wo.mileage_in)
    delta = audit.diff(before, changes)
    if delta:
        if "internal_notes" in delta:
            delta["internal_notes"] = {"changed": True}
        audit.record(
            db,
            user=user,
            action="work_order.updated",
            entity_type="work_order",
            entity_id=wo.id,
            details=delta,
        )
    db.flush()
    return work_order_out(db, wo)


@router.post("/{wo_id}/status", response_model=WorkOrderOut)
def set_status(
    wo_id: int,
    data: StatusChange,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    workflow.change_work_order_status(db, user, wo, data.status, data.override_checklist)
    db.flush()
    out = work_order_out(db, wo)
    if data.notify_customer and data.status == "ready_for_pickup":
        out.email = notify.send_templated(
            db,
            "vehicle_ready",
            wo.customer.email,
            {
                "customer_first_name": wo.customer.first_name,
                "vehicle": wo.vehicle.display_name,
                "document_number": wo.number,
            },
            entity_type="work_order",
            entity_id=wo.id,
        ).as_dict()
        if out.email["status"] == "sent":
            wo.qc_checklist = {**wo.qc_checklist, "customer_notified": True}
    return out


# ---- lines


def _audit_lines(db, user, wo, action, details):
    audit.record(
        db,
        user=user,
        action=action,
        entity_type="work_order",
        entity_id=wo.id,
        details={**details, "total_cents": wo.total_cents},
    )


@router.put("/{wo_id}/items", response_model=WorkOrderOut)
def replace_items(
    wo_id: int,
    items: list[LineItemIn],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    workflow.ensure_work_order_editable(wo)
    workflow.replace_lines(wo, WorkOrderItem, items, get_business(db))
    db.flush()
    _audit_lines(db, user, wo, "work_order.lines_updated", {"line_count": len(items)})
    return work_order_out(db, wo)


@router.post("/{wo_id}/items", response_model=WorkOrderOut, status_code=201)
def add_item(
    wo_id: int, item: LineItemIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    workflow.ensure_work_order_editable(wo)
    line = workflow.append_line(wo, WorkOrderItem, item, get_business(db))
    db.flush()
    _audit_lines(
        db,
        user,
        wo,
        "work_order.line_added",
        {
            "kind": line.kind,
            "description": line.description,
            "line_total_cents": line.line_total_cents,
        },
    )
    return work_order_out(db, wo)


@router.delete("/{wo_id}/items/{item_id}", response_model=WorkOrderOut)
def delete_item(
    wo_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    workflow.ensure_work_order_editable(wo)
    removed = next((li for li in wo.items if li.id == item_id), None)
    workflow.remove_line(wo, item_id)
    db.flush()
    _audit_lines(
        db,
        user,
        wo,
        "work_order.line_removed",
        {"description": removed.description if removed else None},
    )
    return work_order_out(db, wo)


@router.post("/{wo_id}/invoice", response_model=InvoiceOut, status_code=201)
def create_invoice(
    wo_id: int,
    data: InvoiceFromWorkOrder | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    inv = workflow.invoice_from_work_order(db, user, wo, data or InvoiceFromWorkOrder())
    db.flush()
    db.refresh(inv)
    return invoice_out(inv)
