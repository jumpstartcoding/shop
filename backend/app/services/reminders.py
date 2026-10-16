"""Maintenance reminders (spec §16).

A reminder is due when its date is within the shop's lead time, or when the vehicle's last
recorded mileage is within 500 miles of the target. Mileage only moves when the car is seen
(or a past record is added), so date-based reminders are the dependable ones.

Automatic emails are off by default (Settings). When on, the nightly task emails each due
reminder once; the mechanic can always send one by hand. Email is the only channel in V1;
the template and log are channel-agnostic, so SMS can be added later without changing this.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.models import Customer, MaintenanceReminder, User, Vehicle
from app.services import notify
from app.services.business import get_business, shop_today

MILEAGE_WINDOW = 500

# Defaults the app suggests (the mechanic can change any of them).
PRESETS: dict[str, tuple[str, int | None, int | None]] = {
    "oil_change": ("Oil change", 6, 5000),
    "tire_rotation": ("Tire rotation", 6, 6000),
    "brake_inspection": ("Brake inspection", 12, 12000),
    "transmission_service": ("Transmission service", 36, 45000),
    "coolant_service": ("Coolant service", 60, 60000),
    "inspection": ("Inspection", 12, None),
    "custom": ("Service", None, None),
}


def is_due(rem: MaintenanceReminder, vehicle: Vehicle, today: date, lead_days: int) -> bool:
    if rem.status != "open":
        return False
    by_date = rem.due_date is not None and rem.due_date <= today + timedelta(days=lead_days)
    by_miles = (
        rem.due_mileage is not None
        and vehicle.mileage is not None
        and vehicle.mileage >= rem.due_mileage - MILEAGE_WINDOW
    )
    return by_date or by_miles


def due_list(db: Session) -> list[tuple[MaintenanceReminder, Vehicle, Customer]]:
    business = get_business(db)
    today = shop_today(business)
    rows = db.execute(
        select(MaintenanceReminder, Vehicle, Customer)
        .join(Vehicle, Vehicle.id == MaintenanceReminder.vehicle_id)
        .join(Customer, Customer.id == MaintenanceReminder.customer_id)
        .where(
            MaintenanceReminder.status == "open",
            Vehicle.archived_at.is_(None),
            Customer.archived_at.is_(None),
        )
        .order_by(MaintenanceReminder.due_date.asc().nulls_last(), MaintenanceReminder.id)
    ).all()
    return [(r, v, c) for r, v, c in rows if is_due(r, v, today, business.reminder_lead_days)]


def send(db: Session, user: User | None, rem: MaintenanceReminder) -> notify.EmailResult:
    customer = db.get(Customer, rem.customer_id)
    vehicle = db.get(Vehicle, rem.vehicle_id)
    when = []
    if rem.due_date:
        when.append(f"around {rem.due_date:%B %-d, %Y}")
    if rem.due_mileage:
        when.append(f"at {rem.due_mileage:,} miles")
    result = notify.send_templated(
        db,
        "service_reminder",
        customer.email if customer else None,
        {
            "customer_first_name": customer.first_name if customer else "",
            "customer_name": customer.full_name if customer else "",
            "vehicle": vehicle.display_name if vehicle else "vehicle",
            "service": rem.title.lower() + (f" ({' or '.join(when)})" if when else ""),
            "link": f"{get_settings().public_base_url.rstrip('/')}/book",
        },
        entity_type="vehicle",
        entity_id=rem.vehicle_id,
    )
    rem.email_status = result.status
    if result.status == "sent":
        rem.emailed_at = datetime.now(UTC)
    audit.record(
        db,
        user=user,
        actor="user" if user else "system",
        action="reminder.emailed",
        entity_type="vehicle",
        entity_id=rem.vehicle_id,
        details={"reminder_id": rem.id, "status": result.status},
    )
    return result


def nightly(db: Session) -> dict:
    business = get_business(db)
    if not business.reminder_emails:
        return {"reminders_emailed": 0, "reminder_emails": "off"}
    sent = failed = 0
    for rem, _vehicle, customer in due_list(db):
        if rem.emailed_at is not None or not customer.email:
            continue
        result = send(db, None, rem)
        if result.status == "sent":
            sent += 1
        else:
            failed += 1
    return {"reminders_emailed": sent, "reminder_emails_failed": failed}


def reminder_out(
    rem: MaintenanceReminder, vehicle: Vehicle, customer: Customer, today: date, lead: int
) -> dict:
    return {
        "id": rem.id,
        "vehicle_id": rem.vehicle_id,
        "vehicle_name": vehicle.display_name,
        "vehicle_mileage": vehicle.mileage,
        "customer_id": rem.customer_id,
        "customer_name": customer.full_name,
        "customer_email": customer.email,
        "customer_phone": customer.phone,
        "kind": rem.kind,
        "title": rem.title,
        "due_date": rem.due_date,
        "due_mileage": rem.due_mileage,
        "notes": rem.notes,
        "status": rem.status,
        "due": is_due(rem, vehicle, today, lead),
        "overdue": bool(rem.due_date and rem.due_date < today),
        "emailed_at": rem.emailed_at,
        "email_status": rem.email_status,
        "work_order_id": rem.work_order_id,
        "created_at": rem.created_at,
    }
