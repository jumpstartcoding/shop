"""Parts stock follows completed work: parts from the parts list come out of stock when the
work order is completed, and go back if it's reopened. Parts with no quantity set aren't
tracked. Stock may go below zero, which simply means the count needs correcting."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.models import Part, User, WorkOrder


def _parts(db: Session, ids: set[int]) -> dict[int, Part]:
    if not ids:
        return {}
    rows = db.scalars(select(Part).where(Part.id.in_(ids)).order_by(Part.id).with_for_update())
    return {p.id: p for p in rows}


def take_for_completed(db: Session, user: User | None, wo: WorkOrder) -> None:
    lines = [li for li in wo.items if li.part_id and li.kind == "part" and li.stock_qty is None]
    parts = _parts(db, {li.part_id for li in lines})
    used = []
    for li in lines:
        part = parts.get(li.part_id)
        if part is None or part.quantity is None:
            continue
        part.quantity = part.quantity - li.quantity
        li.stock_qty = li.quantity
        used.append({"part_id": part.id, "qty": str(li.quantity), "left": str(part.quantity)})
    if used:
        audit.record(
            db,
            user=user,
            action="parts.stock_used",
            entity_type="work_order",
            entity_id=wo.id,
            details={"parts": used},
        )


def put_back_for_reopened(db: Session, user: User | None, wo: WorkOrder) -> None:
    lines = [li for li in wo.items if li.stock_qty is not None and li.part_id]
    parts = _parts(db, {li.part_id for li in lines})
    returned = []
    for li in lines:
        part = parts.get(li.part_id)
        if part is not None and part.quantity is not None:
            part.quantity = part.quantity + li.stock_qty
            returned.append({"part_id": part.id, "qty": str(li.stock_qty)})
        li.stock_qty = None
    if returned:
        audit.record(
            db,
            user=user,
            action="parts.stock_returned",
            entity_type="work_order",
            entity_id=wo.id,
            details={"parts": returned},
        )
