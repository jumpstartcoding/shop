"""The customer's view of one vehicle (spec §27): its service history, warranties, upcoming
appointments and reminders, and its invoices, through a private link. No account needed.

Only customer-safe fields are included: no internal notes, part costs, or notes typed on
hand-entered records (those can be the shop's own remarks).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.documents.snapshot import _business, _customer, _iso, _vehicle
from app.models import (
    AccessToken,
    Appointment,
    Invoice,
    MaintenanceReminder,
    ServiceRecord,
    Vehicle,
)
from app.services.business import get_business, shop_today
from app.services.history import warranties

SHARED_INVOICE_STATUSES = ("sent", "viewed", "partially_paid", "paid", "overdue")


def _vehicle_for(db: Session, link: AccessToken) -> Vehicle:
    v = db.get(Vehicle, link.entity_id)
    if v is None or v.customer_id != link.customer_id:
        raise NotFound("This vehicle record isn't available.")
    return v


def shared_invoices(db: Session, vehicle: Vehicle) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.vehicle_id == vehicle.id,
                Invoice.customer_id == vehicle.customer_id,
                Invoice.status.in_(SHARED_INVOICE_STATUSES),
            )
            .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
        )
    )


def snapshot(db: Session, link: AccessToken) -> dict:
    vehicle = _vehicle_for(db, link)
    business = get_business(db)
    today = shop_today(business)
    records = list(
        db.scalars(
            select(ServiceRecord)
            .where(ServiceRecord.vehicle_id == vehicle.id, ServiceRecord.deleted_at.is_(None))
            .order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc())
        )
    )
    invoices = shared_invoices(db, vehicle)
    by_id = {i.id: i for i in invoices}
    now = datetime.now(UTC)
    appointments = db.scalars(
        select(Appointment)
        .where(
            Appointment.vehicle_id == vehicle.id,
            Appointment.status.in_(("requested", "confirmed")),
            (Appointment.starts_at.is_(None)) | (Appointment.starts_at >= now),
        )
        .order_by(Appointment.starts_at.asc().nulls_last())
    )
    reminders = db.scalars(
        select(MaintenanceReminder)
        .where(MaintenanceReminder.vehicle_id == vehicle.id, MaintenanceReminder.status == "open")
        .order_by(MaintenanceReminder.due_date.asc().nulls_last())
    )
    return {
        "doc_type": "history",
        "title": "Vehicle service history",
        "number": vehicle.vin
        or " ".join(p for p in [vehicle.license_plate, vehicle.license_state] if p)
        or "Service record",
        "version": None,
        "date": _iso(today),
        "business": _business(business),
        "customer": _customer(vehicle.customer),
        "vehicle": _vehicle(vehicle, None),
        "records": [
            {
                "date": _iso(r.service_date),
                "mileage": r.mileage,
                "summary": r.summary,
                "by_this_shop": r.source == "work_order",
                "performed_by": r.performed_by if r.source == "manual" else None,
                "total_cents": by_id[r.invoice_id].total_cents
                if r.invoice_id in by_id
                else (r.total_cents if r.source == "work_order" else None),
                "invoice_id": r.invoice_id if r.invoice_id in by_id else None,
                "invoice_number": by_id[r.invoice_id].number if r.invoice_id in by_id else None,
            }
            for r in records
        ],
        "warranties": [
            {
                k: _iso(w[k])
                for k in (
                    "description",
                    "service_date",
                    "expires_on",
                    "expires_mileage",
                    "state",
                    "notes",
                )
            }
            for w in warranties(records, vehicle, today)
        ],
        "appointments": [
            {
                "starts_at": _iso(a.starts_at),
                "preferred_date": _iso(a.preferred_date),
                "status": a.status,
                "service": a.requested_service,
            }
            for a in appointments
        ],
        "reminders": [
            {"title": r.title, "due_date": _iso(r.due_date), "due_mileage": r.due_mileage}
            for r in reminders
        ],
        "invoices": [
            {
                "id": i.id,
                "number": i.number,
                "date": _iso(i.issue_date),
                "total_cents": i.total_cents,
                "balance_cents": i.balance_cents,
                "status": i.status,
            }
            for i in invoices
        ],
        "footer": None,
    }


def invoice_for_link(db: Session, link: AccessToken, invoice_id: int) -> Invoice:
    vehicle = _vehicle_for(db, link)
    inv = next((i for i in shared_invoices(db, vehicle) if i.id == invoice_id), None)
    if inv is None:
        raise NotFound("Invoice not found.")
    return inv
