from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_user
from app.db import get_db
from app.models import (
    Appointment,
    AuditLog,
    Customer,
    Estimate,
    Inquiry,
    Invoice,
    Payment,
    User,
    Vehicle,
    WorkOrder,
)
from app.schemas.common import digits_only
from app.services.business import get_business, shop_now
from app.services.serialize import work_order_card
from app.services.workflow import TERMINAL_WO

router = APIRouter(tags=["dashboard"])

UNPAID = ("sent", "viewed", "partially_paid", "overdue")
IN_SHOP = (
    "checked_in",
    "diagnosing",
    "waiting_approval",
    "approved",
    "in_repair",
    "quality_check",
    "ready_for_pickup",
)


def _revenue_since(db: Session, since: datetime) -> int:
    return int(
        db.scalar(
            # Net of refunds. A refund is counted against the period of the original payment;
            # this is a working view of cash in, not an accounting ledger.
            select(func.coalesce(func.sum(Payment.amount_cents - Payment.refunded_cents), 0)).where(
                Payment.status.in_(("succeeded", "refunded")), Payment.paid_at >= since
            )
        )
        or 0
    )


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_user)):
    """Everything the mechanic needs to see at a glance, in one request."""
    business = get_business(db)
    tz = ZoneInfo(business.timezone)
    now = shop_now(business)
    today = now.date()
    day_start = datetime.combine(today, time.min, tz)
    week_start = day_start - timedelta(days=today.weekday())
    month_start = datetime.combine(today.replace(day=1), time.min, tz)
    year_start = datetime.combine(today.replace(month=1, day=1), time.min, tz)

    def appt_row(a: Appointment):
        return {
            "id": a.id,
            "status": a.status,
            "starts_at": a.starts_at,
            "customer_name": a.customer.full_name if a.customer else a.contact_name,
            "vehicle_name": a.vehicle.display_name if a.vehicle else a.vehicle_description,
            "requested_service": a.requested_service,
        }

    active = ("requested", "confirmed", "checked_in", "in_progress")
    todays = db.scalars(
        select(Appointment)
        .where(
            Appointment.starts_at >= day_start,
            Appointment.starts_at < day_start + timedelta(days=1),
            Appointment.status.in_(active + ("completed",)),
        )
        .order_by(Appointment.starts_at)
    )
    upcoming = db.scalars(
        select(Appointment)
        .where(
            Appointment.starts_at >= day_start + timedelta(days=1),
            Appointment.starts_at < day_start + timedelta(days=8),
            Appointment.status.in_(active),
        )
        .order_by(Appointment.starts_at)
        .limit(20)
    )
    requests = list(
        db.scalars(
            select(Appointment)
            .where(Appointment.status == "requested")
            .order_by(Appointment.created_at.desc())
            .limit(20)
        )
    )

    open_wos = list(
        db.scalars(
            select(WorkOrder)
            .where(WorkOrder.status.not_in(TERMINAL_WO))
            .order_by(WorkOrder.promised_at.asc().nulls_last(), WorkOrder.created_at)
        )
    )
    pending_estimates = list(
        db.scalars(
            select(Estimate)
            .where(Estimate.status.in_(("sent", "viewed")))
            .order_by(Estimate.sent_at)
        )
    )
    unpaid = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.status.in_(UNPAID))
            .order_by(Invoice.due_date.asc().nulls_last())
        )
    )
    overdue = [i for i in unpaid if i.due_date and i.due_date < today]
    recently_paid = db.scalars(
        select(Invoice).where(Invoice.status == "paid").order_by(Invoice.paid_at.desc()).limit(5)
    )

    def inv_row(i: Invoice):
        return {
            "id": i.id,
            "number": i.number,
            "status": i.status,
            "customer_name": i.customer.full_name,
            "total_cents": i.total_cents,
            "balance_cents": i.balance_cents,
            "due_date": i.due_date,
            "paid_at": i.paid_at,
        }

    messages = list(
        db.scalars(
            select(Inquiry)
            .where(Inquiry.handled_at.is_(None))
            .order_by(Inquiry.created_at.desc())
            .limit(20)
        )
    )
    notifications = []
    if messages:
        notifications.append(
            {
                "kind": "messages",
                "count": len(messages),
                "message": f"{len(messages)} message{'s' if len(messages) != 1 else ''} "
                "from customers to answer.",
            }
        )
    if requests:
        notifications.append(
            {
                "kind": "appointment_requests",
                "count": len(requests),
                "message": f"{len(requests)} new appointment request"
                f"{'s' if len(requests) != 1 else ''} to review.",
            }
        )
    ready = [w for w in open_wos if w.status == "ready_for_pickup"]
    if ready:
        notifications.append(
            {
                "kind": "ready_for_pickup",
                "count": len(ready),
                "message": f"{len(ready)} vehicle{'s' if len(ready) != 1 else ''} "
                "ready for pickup.",
            }
        )
    if pending_estimates:
        notifications.append(
            {
                "kind": "estimates_awaiting",
                "count": len(pending_estimates),
                "message": f"{len(pending_estimates)} estimate"
                f"{'s' if len(pending_estimates) != 1 else ''} "
                "waiting on the customer.",
            }
        )
    if overdue:
        notifications.append(
            {
                "kind": "invoices_overdue",
                "count": len(overdue),
                "message": f"{len(overdue)} overdue invoice{'s' if len(overdue) != 1 else ''}.",
            }
        )
    online_today = list(
        db.scalars(
            select(Payment).where(
                Payment.method == "online",
                Payment.status.in_(("succeeded", "refunded")),
                Payment.paid_at >= now - timedelta(hours=24),
            )
        )
    )
    if online_today:
        total = sum(p.amount_cents for p in online_today)
        notifications.append(
            {
                "kind": "online_payments",
                "count": len(online_today),
                "message": f"{len(online_today)} online payment{'s' if len(online_today) != 1 else ''}"
                f" received in the last day, ${total / 100:,.2f} total.",
            }
        )
    needs_refund = [
        i
        for i in db.scalars(
            select(Invoice).where(
                Invoice.amount_paid_cents > 0,
                (Invoice.amount_paid_cents > Invoice.total_cents) | (Invoice.status == "void"),
            )
        )
        if i.overpaid_cents
    ]
    for i in needs_refund:
        notifications.insert(
            0,
            {
                "kind": "needs_refund",
                "count": 1,
                "entity_id": i.id,
                "message": f"Invoice {i.number} is overpaid by ${i.overpaid_cents / 100:,.2f}. "
                "Refund the difference.",
            },
        )

    return {
        "as_of": now,
        "notifications": notifications,
        "appointments_today": [appt_row(a) for a in todays],
        "appointments_upcoming": [appt_row(a) for a in upcoming],
        "appointment_requests": [appt_row(a) for a in requests],
        "open_work_orders": [work_order_card(w) for w in open_wos],
        "vehicles_in_shop": [work_order_card(w) for w in open_wos if w.status in IN_SHOP],
        "pending_estimates": [
            {
                "id": e.id,
                "number": e.number,
                "status": e.status,
                "customer_name": e.customer.full_name,
                "total_cents": e.total_cents,
                "sent_at": e.sent_at,
            }
            for e in pending_estimates
        ],
        "unpaid_invoices": [inv_row(i) for i in unpaid],
        "recently_paid_invoices": [inv_row(i) for i in recently_paid],
        "revenue": {
            "today_cents": _revenue_since(db, day_start),
            "week_cents": _revenue_since(db, week_start),
            "month_cents": _revenue_since(db, month_start),
            "year_cents": _revenue_since(db, year_start),
        },
        "outstanding_cents": sum(i.balance_cents for i in unpaid),
        "messages": [
            {
                "id": m.id,
                "kind": m.kind,
                "name": m.name,
                "message": m.message[:200],
                "entity_type": m.entity_type,
                "entity_id": m.entity_id,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }


@router.get("/search")
def search(
    q: str = Query(..., min_length=2, max_length=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    """Global search across customers, vehicles, and document numbers."""
    term = q.strip()
    like = f"%{term.lower()}%"
    upper = term.upper().replace(" ", "")
    digits = digits_only(term)

    cust_conds = [
        func.lower(Customer.first_name + " " + Customer.last_name).like(like),
        func.lower(Customer.email).like(like),
    ]
    if digits and len(digits) >= 3:
        cust_conds.append(Customer.phone_digits.like(f"%{digits}%"))
    customers = db.scalars(
        select(Customer)
        .where(or_(*cust_conds))
        .order_by(Customer.archived_at.is_not(None), Customer.last_name)
        .limit(8)
    )
    vehicles = db.scalars(
        select(Vehicle)
        .where(
            or_(
                Vehicle.vin.like(f"%{upper}%"),
                func.upper(Vehicle.license_plate).like(f"%{upper}%"),
                func.lower(func.concat_ws(" ", Vehicle.year, Vehicle.make, Vehicle.model)).like(
                    like
                ),
            )
        )
        .order_by(Vehicle.archived_at.is_not(None), Vehicle.id.desc())
        .limit(8)
    )

    def docs(model, kind):
        return [
            {
                "kind": kind,
                "id": d.id,
                "number": d.number,
                "status": d.status,
                "customer_name": d.customer.full_name,
                "total_cents": d.total_cents,
            }
            for d in db.scalars(
                select(model)
                .where(func.lower(model.number).like(like))
                .order_by(model.id.desc())
                .limit(5)
            )
        ]

    return {
        "customers": [
            {
                "id": c.id,
                "name": c.full_name,
                "phone": c.phone,
                "email": c.email,
                "archived": c.archived_at is not None,
            }
            for c in customers
        ],
        "vehicles": [
            {
                "id": v.id,
                "customer_id": v.customer_id,
                "name": v.display_name,
                "vin": v.vin,
                "license_plate": v.license_plate,
                "owner": v.customer.full_name,
                "archived": v.archived_at is not None,
            }
            for v in vehicles
        ],
        "documents": docs(WorkOrder, "work_order")
        + docs(Estimate, "estimate")
        + docs(Invoice, "invoice"),
    }


@router.get("/audit")
def audit_log(
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    stmt = select(AuditLog, User.name).outerjoin(User, User.id == AuditLog.user_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    rows = db.execute(stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit))
    return [
        {
            "id": a.id,
            "occurred_at": a.occurred_at,
            "actor": a.actor,
            "user_name": name,
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "details": a.details,
        }
        for a, name in rows
    ]
