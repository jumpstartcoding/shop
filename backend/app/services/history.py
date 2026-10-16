"""Vehicle service history and warranties (spec §15, §34).

Completing a work order writes (or rewrites) its service record; reopening hides it until it
is completed again. Records can also be added by hand for work done before the shop used
the app, or done elsewhere. Warranties come from the warranty fields on the lines of each
record, so they appear on the vehicle without any extra typing.
"""

import calendar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict
from app.models import Invoice, ServiceRecord, User, Vehicle, WorkOrder
from app.services.business import get_business, shop_today


def _summary(wo: WorkOrder) -> str:
    work = [li.description for li in wo.items if li.kind in ("labor", "part")]
    return ("; ".join(work) or wo.concern or f"Work order {wo.number}")[:500]


def _lines(items) -> list[dict]:
    return [
        {
            "kind": li.kind,
            "description": li.description,
            "quantity": str(li.quantity),
            "part_number": li.part_number,
            "warranty_months": li.warranty_months,
            "warranty_miles": li.warranty_miles,
            "warranty_notes": li.warranty_notes,
        }
        for li in items
        if li.kind != "discount"
    ]


def _invoice_for(db: Session, wo_id: int) -> Invoice | None:
    return db.scalar(
        select(Invoice)
        .where(Invoice.work_order_id == wo_id, Invoice.status != "void")
        .order_by(Invoice.id.desc())
        .limit(1)
    )


def record_completion(db: Session, wo: WorkOrder) -> ServiceRecord:
    """Called when a work order is marked completed."""
    business = get_business(db)
    when = (wo.completed_at or datetime.now(UTC)).astimezone(ZoneInfo(business.timezone)).date()
    inv = _invoice_for(db, wo.id)
    rec = db.scalar(select(ServiceRecord).where(ServiceRecord.work_order_id == wo.id))
    if rec is None:
        rec = ServiceRecord(work_order_id=wo.id, source="work_order")
        db.add(rec)
    rec.vehicle_id = wo.vehicle_id
    rec.customer_id = wo.customer_id
    rec.service_date = when
    rec.mileage = wo.mileage_out or wo.mileage_in
    rec.summary = _summary(wo)
    rec.lines = _lines(wo.items)
    rec.labor_cents = wo.labor_cents
    rec.parts_cents = wo.parts_cents
    rec.invoice_id = inv.id if inv else None
    rec.total_cents = inv.total_cents if inv else wo.total_cents
    rec.notes = wo.customer_notes
    rec.deleted_at = None
    db.flush()
    return rec


def hide_for_reopened(db: Session, wo: WorkOrder) -> None:
    rec = db.scalar(select(ServiceRecord).where(ServiceRecord.work_order_id == wo.id))
    if rec is not None and rec.deleted_at is None:
        rec.deleted_at = datetime.now(UTC)
        db.flush()


def invoice_changed(db: Session, inv: Invoice) -> None:
    """Keep the record's invoice link and total in step when an invoice for a completed job
    is created or voided."""
    if not inv.work_order_id:
        return
    rec = db.scalar(select(ServiceRecord).where(ServiceRecord.work_order_id == inv.work_order_id))
    if rec is None:
        return
    current = _invoice_for(db, inv.work_order_id)
    rec.invoice_id = current.id if current else None
    if current:
        rec.total_cents = current.total_cents
    else:
        wo = db.get(WorkOrder, inv.work_order_id)
        rec.total_cents = wo.total_cents if wo else rec.total_cents


def add_manual(db: Session, user: User, vehicle: Vehicle, data: dict) -> ServiceRecord:
    rec = ServiceRecord(
        vehicle_id=vehicle.id,
        customer_id=vehicle.customer_id,
        source="manual",
        service_date=data["service_date"],
        mileage=data.get("mileage"),
        summary=data["summary"],
        lines=[],
        notes=data.get("notes"),
        performed_by=data.get("performed_by"),
        total_cents=data.get("total_cents"),
    )
    db.add(rec)
    db.flush()
    if rec.mileage and (vehicle.mileage or 0) < rec.mileage:
        vehicle.mileage = rec.mileage
    audit.record(
        db,
        user=user,
        action="service_record.added",
        entity_type="vehicle",
        entity_id=vehicle.id,
        details={"record_id": rec.id, "date": str(rec.service_date)},
    )
    return rec


def update_manual(db: Session, user: User, rec: ServiceRecord, data: dict) -> None:
    if rec.source != "manual":
        raise Conflict(
            "This record comes from a completed work order. Change the work order instead."
        )
    for k, v in data.items():
        setattr(rec, k, v)
    db.flush()
    audit.record(
        db,
        user=user,
        action="service_record.updated",
        entity_type="vehicle",
        entity_id=rec.vehicle_id,
        details={"record_id": rec.id, "fields": sorted(data)},
    )


def remove_manual(db: Session, user: User, rec: ServiceRecord) -> None:
    if rec.source != "manual":
        raise Conflict("Records from completed work orders can't be removed here.")
    rec.deleted_at = datetime.now(UTC)
    db.flush()  # sessions don't autoflush; the history read that follows must see this
    audit.record(
        db,
        user=user,
        action="service_record.removed",
        entity_type="vehicle",
        entity_id=rec.vehicle_id,
        details={"record_id": rec.id},
    )


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def warranties(records: list[ServiceRecord], vehicle: Vehicle, today: date) -> list[dict]:
    out = []
    for rec in records:
        for line in rec.lines or []:
            months, miles = line.get("warranty_months"), line.get("warranty_miles")
            if not (months or miles or line.get("warranty_notes")):
                continue
            expires_on = add_months(rec.service_date, months) if months else None
            expires_mileage = rec.mileage + miles if miles and rec.mileage is not None else None
            expired = bool(expires_on and today > expires_on) or bool(
                expires_mileage and vehicle.mileage and vehicle.mileage > expires_mileage
            )
            if expires_on is None and expires_mileage is None:
                state = "see_notes"
            else:
                state = "expired" if expired else "active"
            out.append(
                {
                    "record_id": rec.id,
                    "service_date": rec.service_date,
                    "description": line["description"],
                    "kind": line["kind"],
                    "part_number": line.get("part_number"),
                    "months": months,
                    "miles": miles,
                    "notes": line.get("warranty_notes"),
                    "expires_on": expires_on,
                    "expires_mileage": expires_mileage,
                    "state": state,
                }
            )
    rank = {"active": 0, "see_notes": 1, "expired": 2}
    out.sort(key=lambda w: (rank[w["state"]], w["expires_on"] or date.max))
    return out


def vehicle_history(db: Session, vehicle: Vehicle) -> dict:
    records = list(
        db.scalars(
            select(ServiceRecord)
            .where(ServiceRecord.vehicle_id == vehicle.id, ServiceRecord.deleted_at.is_(None))
            .order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc())
        )
    )
    wo_numbers = dict(
        db.execute(
            select(WorkOrder.id, WorkOrder.number).where(
                WorkOrder.id.in_([r.work_order_id for r in records if r.work_order_id])
            )
        ).all()
    )
    invoices = {
        row.id: row
        for row in db.execute(
            select(Invoice.id, Invoice.number, Invoice.total_cents).where(
                Invoice.id.in_([r.invoice_id for r in records if r.invoice_id])
            )
        )
    }
    today = shop_today(get_business(db))
    return {
        "records": [
            {
                "id": r.id,
                "source": r.source,
                "service_date": r.service_date,
                "mileage": r.mileage,
                "summary": r.summary,
                "lines": r.lines,
                "labor_cents": r.labor_cents,
                "parts_cents": r.parts_cents,
                # The invoice's current total (it can still be edited until paid).
                "total_cents": invoices[r.invoice_id].total_cents
                if r.invoice_id in invoices
                else r.total_cents,
                "notes": r.notes,
                "performed_by": r.performed_by,
                "work_order": {"id": r.work_order_id, "number": wo_numbers.get(r.work_order_id)}
                if r.work_order_id
                else None,
                "invoice": {"id": r.invoice_id, "number": invoices[r.invoice_id].number}
                if r.invoice_id in invoices
                else None,
            }
            for r in records
        ],
        "warranties": warranties(records, vehicle, today),
    }
