"""Workflows that span tables: work orders, estimates, invoices, payments.

Rules that protect money and records live here, not in the routers:
- issued documents are changed only through explicit, audited actions;
- an invoice's lines can't change once money has been received against it;
- payment totals are recomputed with the invoice row locked.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import AppError, Conflict, NotFound
from app.core.numbering import next_number
from app.models import (
    Appointment,
    Business,
    Customer,
    Estimate,
    EstimateItem,
    Invoice,
    InvoiceItem,
    Payment,
    User,
    Vehicle,
    WorkOrder,
    WorkOrderItem,
)
from app.models.documents import QC_CHECKLIST_KEYS
from app.schemas.documents import (
    DecisionIn,
    EstimateCreate,
    InvoiceCreate,
    InvoiceFromWorkOrder,
    LineItemIn,
    PaymentIn,
    WorkOrderCreate,
)
from app.services.business import get_business, shop_today
from app.services.lines import apply_totals, build_line, copy_line


def _now() -> datetime:
    return datetime.now(UTC)


class InvalidReference(AppError):
    status_code = 422
    code = "invalid_reference"


# ---------------------------------------------------------------- lookups


def get_or_404(db: Session, model, obj_id: int, label: str, *, lock: bool = False):
    stmt = select(model).where(model.id == obj_id)
    if lock:
        stmt = stmt.with_for_update()
    obj = db.scalar(stmt)
    if obj is None:
        raise NotFound(f"{label} not found.")
    return obj


def customer_and_vehicle(
    db: Session, customer_id: int, vehicle_id: int
) -> tuple[Customer, Vehicle]:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.archived_at is not None:
        raise InvalidReference("That customer doesn't exist or has been archived.")
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.archived_at is not None:
        raise InvalidReference("That vehicle doesn't exist or has been archived.")
    if vehicle.customer_id != customer.id:
        raise InvalidReference("That vehicle doesn't belong to this customer.")
    return customer, vehicle


def _bump_mileage(vehicle: Vehicle, mileage: int | None) -> None:
    if mileage is not None and (vehicle.mileage is None or mileage > vehicle.mileage):
        vehicle.mileage = mileage


# ---------------------------------------------------------------- line editing (shared)


def replace_lines(doc, item_model, items: list[LineItemIn], business: Business) -> None:
    doc.items.clear()
    for i, data in enumerate(items):
        doc.items.append(build_line(item_model, data, business, i))
    apply_totals(doc, doc.items, doc.tax_rate)


def append_line(doc, item_model, data: LineItemIn, business: Business):
    position = max((li.position for li in doc.items), default=-1) + 1
    line = build_line(item_model, data, business, position)
    doc.items.append(line)
    apply_totals(doc, doc.items, doc.tax_rate)
    return line


def remove_line(doc, item_id: int) -> None:
    for line in doc.items:
        if line.id == item_id:
            doc.items.remove(line)
            apply_totals(doc, doc.items, doc.tax_rate)
            return
    raise NotFound("Line item not found.")


# ---------------------------------------------------------------- work orders

TERMINAL_WO = {"completed", "cancelled"}


def create_work_order(db: Session, user: User, data: WorkOrderCreate) -> WorkOrder:
    business = get_business(db)
    customer, vehicle = customer_and_vehicle(db, data.customer_id, data.vehicle_id)
    wo = WorkOrder(
        number=next_number(db, "work_order", business.work_order_prefix, shop_today(business).year),
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        status="new",
        concern=data.concern,
        customer_notes=data.customer_notes,
        internal_notes=data.internal_notes,
        mileage_in=data.mileage_in,
        promised_at=data.promised_at,
        qc_checklist={},
        tax_rate=business.tax_rate,
    )
    db.add(wo)
    replace_lines(wo, WorkOrderItem, data.items, business)
    _bump_mileage(vehicle, data.mileage_in)
    db.flush()

    if data.appointment_id is not None:
        appt = get_or_404(db, Appointment, data.appointment_id, "Appointment")
        if appt.customer_id not in (None, customer.id):
            raise InvalidReference("That appointment belongs to a different customer.")
        appt.work_order_id = wo.id
        appt.customer_id = customer.id
        appt.vehicle_id = vehicle.id
        if appt.status in ("requested", "confirmed"):
            appt.status = "checked_in"
            wo.status = "checked_in"

    audit.record(
        db,
        user=user,
        action="work_order.created",
        entity_type="work_order",
        entity_id=wo.id,
        details={"number": wo.number},
    )
    return wo


def ensure_work_order_editable(wo: WorkOrder) -> None:
    if wo.status in TERMINAL_WO:
        raise Conflict(
            f"Work order {wo.number} is {wo.status.replace('_', ' ')}. Reopen it to make changes."
        )


def change_work_order_status(
    db: Session, user: User, wo: WorkOrder, status: str, override_checklist: bool
) -> None:
    previous = wo.status
    if status == previous:
        return
    if status == "completed":
        missing = [k for k in QC_CHECKLIST_KEYS if not wo.qc_checklist.get(k)]
        if missing and not override_checklist:
            raise Conflict(
                "Finish the completion checklist first: "
                + ", ".join(k.replace("_", " ") for k in missing)
                + ".",
                code="checklist_incomplete",
            )
        wo.completed_at = _now()
        vehicle = db.get(Vehicle, wo.vehicle_id)
        _bump_mileage(vehicle, wo.mileage_out or wo.mileage_in)
    elif previous == "completed":
        wo.completed_at = None
    wo.status = status
    audit.record(
        db,
        user=user,
        action="work_order.status_changed",
        entity_type="work_order",
        entity_id=wo.id,
        details={
            "from": previous,
            "to": status,
            **(
                {"checklist_overridden": True}
                if status == "completed" and override_checklist
                else {}
            ),
        },
    )


# ---------------------------------------------------------------- estimates

EDITABLE_ESTIMATE = {"draft"}


def create_estimate(db: Session, user: User, data: EstimateCreate) -> Estimate:
    business = get_business(db)
    customer, vehicle = customer_and_vehicle(db, data.customer_id, data.vehicle_id)
    wo = None
    if data.work_order_id is not None:
        wo = get_or_404(db, WorkOrder, data.work_order_id, "Work order")
        if wo.customer_id != customer.id or wo.vehicle_id != vehicle.id:
            raise InvalidReference("That work order is for a different customer or vehicle.")

    today = shop_today(business)
    est = Estimate(
        number=next_number(db, "estimate", business.estimate_prefix, today.year),
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        work_order_id=wo.id if wo else None,
        status="draft",
        concern=data.concern or (wo.concern if wo else None),
        customer_notes=data.customer_notes,
        internal_notes=data.internal_notes,
        mileage=data.mileage or (wo.mileage_in if wo else None) or vehicle.mileage,
        expires_on=data.expires_on or today + timedelta(days=business.estimate_valid_days),
        tax_rate=business.tax_rate,
    )
    db.add(est)
    if data.items is None and wo is not None:
        for i, src in enumerate(wo.items):
            est.items.append(copy_line(EstimateItem, src, i))
        apply_totals(est, est.items, est.tax_rate)
    else:
        replace_lines(est, EstimateItem, data.items or [], business)
    db.flush()
    audit.record(
        db,
        user=user,
        action="estimate.created",
        entity_type="estimate",
        entity_id=est.id,
        details={"number": est.number, "total_cents": est.total_cents},
    )
    return est


def ensure_estimate_editable(est: Estimate) -> None:
    if est.status not in EDITABLE_ESTIMATE or est.locked_at is not None:
        raise Conflict(
            f"Estimate {est.number} has been {est.status}. Create a new version to change it.",
            code="estimate_locked",
        )


def mark_estimate_sent(db: Session, user: User, est: Estimate) -> None:
    if est.status != "draft":
        raise Conflict(f"Estimate {est.number} is already {est.status}.")
    if not est.items:
        raise Conflict("Add at least one line before sending the estimate.")
    est.status = "sent"
    est.sent_at = est.locked_at = _now()
    audit.record(
        db,
        user=user,
        action="estimate.sent",
        entity_type="estimate",
        entity_id=est.id,
        details={"version": est.version, "total_cents": est.total_cents, "channel": "manual"},
    )


def record_estimate_decision(db: Session, user: User, est: Estimate, data: DecisionIn) -> None:
    """Record approval or decline the customer gave in person or by phone/email/text."""
    if est.status not in ("draft", "sent", "viewed"):
        raise Conflict(f"Estimate {est.number} is already {est.status}.")
    if not est.items:
        raise Conflict("An estimate with no lines can't be approved.")
    now = _now()
    est.status = data.decision
    est.locked_at = est.locked_at or now
    est.decision_method = data.method
    est.decision_note = data.note
    if data.decision == "approved":
        est.approved_at = now
        if est.work_order_id:
            wo = db.get(WorkOrder, est.work_order_id)
            if wo and wo.status in ("new", "checked_in", "diagnosing", "waiting_approval"):
                wo.status = "approved"
    else:
        est.declined_at = now
    audit.record(
        db,
        user=user,
        action=f"estimate.{data.decision}",
        entity_type="estimate",
        entity_id=est.id,
        details={
            "version": est.version,
            "total_cents": est.total_cents,
            "method": data.method,
            "note": data.note,
            "recorded_by": "mechanic",
        },
    )


def revise_estimate(db: Session, user: User, est: Estimate) -> None:
    if est.converted_at is not None:
        raise Conflict("This estimate was already turned into work. Create a new estimate instead.")
    if est.status == "draft":
        raise Conflict("This estimate is still a draft; edit it directly.")
    previous = {"version": est.version, "status": est.status, "total_cents": est.total_cents}
    est.version += 1
    est.status = "draft"
    est.sent_at = est.viewed_at = est.approved_at = est.declined_at = est.locked_at = None
    est.decision_method = est.decision_note = None
    audit.record(
        db,
        user=user,
        action="estimate.revised",
        entity_type="estimate",
        entity_id=est.id,
        details={"previous": previous, "new_version": est.version},
    )


def convert_estimate(db: Session, user: User, est: Estimate) -> WorkOrder:
    if est.status != "approved":
        raise Conflict("Only an approved estimate can be turned into a work order.")
    if est.converted_at is not None:
        raise Conflict("This estimate has already been added to a work order.")
    business = get_business(db)

    if est.work_order_id:
        wo = get_or_404(db, WorkOrder, est.work_order_id, "Work order")
        ensure_work_order_editable(wo)
        # The estimate was usually built from this work order's own lines. Replace them with
        # the approved lines rather than appending, so approved work isn't counted twice.
        # The lines being replaced are written to the audit log so nothing disappears silently.
        replaced = [
            {"kind": li.kind, "description": li.description, "total_cents": li.line_total_cents}
            for li in wo.items
        ]
        if replaced:
            audit.record(
                db,
                user=user,
                action="work_order.lines_replaced",
                entity_type="work_order",
                entity_id=wo.id,
                details={"by_estimate": est.number, "replaced": replaced},
            )
        wo.items.clear()
        for i, src in enumerate(est.items):
            wo.items.append(copy_line(WorkOrderItem, src, i))
        apply_totals(wo, wo.items, wo.tax_rate)
        if wo.status in ("new", "checked_in", "diagnosing", "waiting_approval"):
            wo.status = "approved"
    else:
        wo = WorkOrder(
            number=next_number(
                db, "work_order", business.work_order_prefix, shop_today(business).year
            ),
            customer_id=est.customer_id,
            vehicle_id=est.vehicle_id,
            status="approved",
            concern=est.concern,
            customer_notes=est.customer_notes,
            mileage_in=est.mileage,
            qc_checklist={},
            tax_rate=est.tax_rate,
        )
        db.add(wo)
        for i, src in enumerate(est.items):
            wo.items.append(copy_line(WorkOrderItem, src, i))
        apply_totals(wo, wo.items, wo.tax_rate)
        db.flush()
        est.work_order_id = wo.id
        audit.record(
            db,
            user=user,
            action="work_order.created",
            entity_type="work_order",
            entity_id=wo.id,
            details={"number": wo.number, "from_estimate": est.number},
        )

    est.converted_at = _now()
    audit.record(
        db,
        user=user,
        action="estimate.converted",
        entity_type="estimate",
        entity_id=est.id,
        details={"work_order": wo.number},
    )
    return wo


# ---------------------------------------------------------------- invoices

PAID_LIKE = {"paid", "partially_paid"}


def settle_invoice_status(inv: Invoice, today: date) -> None:
    """Derive status from payments, sending, and due date. Void is final."""
    if inv.status == "void":
        return
    if inv.amount_paid_cents > 0 and inv.amount_paid_cents >= inv.total_cents:
        inv.status = "paid"
        inv.paid_at = inv.paid_at or _now()
        return
    inv.paid_at = None
    if inv.amount_paid_cents > 0:
        inv.status = "partially_paid"
        return
    base = "viewed" if inv.viewed_at else "sent" if inv.sent_at else "draft"
    if base != "draft" and inv.due_date is not None and inv.due_date < today:
        base = "overdue"
    inv.status = base


def _new_invoice(db: Session, business: Business, **fields) -> Invoice:
    today = shop_today(business)
    issue = fields.pop("issue_date", None) or today
    due = fields.pop("due_date", None) or issue + timedelta(days=business.invoice_due_days)
    if due < issue:
        raise AppError(
            "The due date can't be before the invoice date.",
            status_code=422,
            code="validation_error",
        )
    inv = Invoice(
        number=next_number(db, "invoice", business.invoice_prefix, issue.year),
        status="draft",
        issue_date=issue,
        due_date=due,
        tax_rate=business.tax_rate,
        amount_paid_cents=0,
        **fields,
    )
    db.add(inv)
    return inv


def create_invoice(db: Session, user: User, data: InvoiceCreate) -> Invoice:
    business = get_business(db)
    customer, vehicle = customer_and_vehicle(db, data.customer_id, data.vehicle_id)
    inv = _new_invoice(
        db,
        business,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        issue_date=data.issue_date,
        due_date=data.due_date,
        mileage=data.mileage or vehicle.mileage,
        customer_notes=data.customer_notes,
        internal_notes=data.internal_notes,
    )
    replace_lines(inv, InvoiceItem, data.items, business)
    db.flush()
    audit.record(
        db,
        user=user,
        action="invoice.created",
        entity_type="invoice",
        entity_id=inv.id,
        details={"number": inv.number, "total_cents": inv.total_cents},
    )
    return inv


def invoice_from_work_order(
    db: Session, user: User, wo: WorkOrder, data: InvoiceFromWorkOrder
) -> Invoice:
    if wo.status == "cancelled":
        raise Conflict("A cancelled work order can't be invoiced.")
    if not wo.items:
        raise Conflict("Add parts or labor to the work order before invoicing it.")
    existing = db.scalar(
        select(Invoice).where(Invoice.work_order_id == wo.id, Invoice.status != "void")
    )
    if existing:
        raise Conflict(
            f"This work order already has invoice {existing.number}.", code="already_invoiced"
        )
    business = get_business(db)
    inv = _new_invoice(
        db,
        business,
        customer_id=wo.customer_id,
        vehicle_id=wo.vehicle_id,
        work_order_id=wo.id,
        due_date=data.due_date,
        mileage=wo.mileage_out or wo.mileage_in,
        customer_notes=data.customer_notes or wo.customer_notes,
    )
    inv.tax_rate = wo.tax_rate
    for i, src in enumerate(wo.items):
        inv.items.append(copy_line(InvoiceItem, src, i))
    apply_totals(inv, inv.items, inv.tax_rate)
    wo.qc_checklist = {**wo.qc_checklist, "invoice_generated": True}
    db.flush()
    audit.record(
        db,
        user=user,
        action="invoice.created",
        entity_type="invoice",
        entity_id=inv.id,
        details={"number": inv.number, "total_cents": inv.total_cents, "work_order": wo.number},
    )
    return inv


def ensure_invoice_editable(inv: Invoice) -> None:
    if inv.status == "void":
        raise Conflict(f"Invoice {inv.number} is void.")
    if inv.amount_paid_cents > 0:
        raise Conflict(
            f"Invoice {inv.number} has payments recorded, so its charges can't change. "
            "Void the payments first, or void this invoice and issue a new one.",
            code="invoice_has_payments",
        )


def mark_invoice_sent(db: Session, user: User, inv: Invoice) -> None:
    if inv.status == "void":
        raise Conflict(f"Invoice {inv.number} is void.")
    if not inv.items:
        raise Conflict("Add at least one line before sending the invoice.")
    if inv.sent_at is None:
        inv.sent_at = _now()
    settle_invoice_status(inv, shop_today(get_business(db)))
    audit.record(
        db,
        user=user,
        action="invoice.sent",
        entity_type="invoice",
        entity_id=inv.id,
        details={"total_cents": inv.total_cents, "channel": "manual"},
    )


def void_invoice(db: Session, user: User, inv: Invoice, reason: str) -> None:
    if inv.status == "void":
        raise Conflict(f"Invoice {inv.number} is already void.")
    live = db.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.invoice_id == inv.id, Payment.status == "succeeded")
    )
    if live:
        raise Conflict(
            "Void or refund this invoice's payments before voiding it.", code="invoice_has_payments"
        )
    inv.status = "void"
    inv.voided_at = _now()
    inv.void_reason = reason
    audit.record(
        db,
        user=user,
        action="invoice.voided",
        entity_type="invoice",
        entity_id=inv.id,
        details={"reason": reason, "total_cents": inv.total_cents},
    )


# ---------------------------------------------------------------- payments


def record_manual_payment(db: Session, user: User, invoice_id: int, data: PaymentIn) -> Payment:
    inv = get_or_404(db, Invoice, invoice_id, "Invoice", lock=True)
    if inv.status == "void":
        raise Conflict(f"Invoice {inv.number} is void; payments can't be recorded against it.")
    if data.method == "online":
        raise AppError(
            "Online payments are recorded automatically when the customer pays.",
            status_code=422,
            code="validation_error",
        )
    balance = inv.total_cents - inv.amount_paid_cents
    if balance <= 0:
        raise Conflict(f"Invoice {inv.number} is already paid in full.")
    if data.amount_cents > balance:
        raise Conflict(
            f"That's more than the ${balance / 100:,.2f} balance on invoice {inv.number}.",
            code="overpayment",
        )
    paid_at = data.paid_at or _now()
    if paid_at.tzinfo is None:
        raise AppError(
            "Payment time must include a time zone.", status_code=422, code="validation_error"
        )
    payment = Payment(
        invoice_id=inv.id,
        amount_cents=data.amount_cents,
        method=data.method,
        status="succeeded",
        paid_at=paid_at,
        reference=data.reference,
        notes=data.notes,
        recorded_by_user_id=user.id,
    )
    db.add(payment)
    inv.amount_paid_cents += data.amount_cents
    settle_invoice_status(inv, shop_today(get_business(db)))
    db.flush()
    audit.record(
        db,
        user=user,
        action="payment.recorded",
        entity_type="invoice",
        entity_id=inv.id,
        details={
            "payment_id": payment.id,
            "amount_cents": payment.amount_cents,
            "method": payment.method,
            "balance_cents": inv.balance_cents,
        },
    )
    return payment


def void_manual_payment(db: Session, user: User, payment_id: int, reason: str) -> Payment:
    payment = get_or_404(db, Payment, payment_id, "Payment")
    inv = get_or_404(db, Invoice, payment.invoice_id, "Invoice", lock=True)
    db.refresh(payment, with_for_update=True)
    if payment.status != "succeeded":
        raise Conflict(f"This payment is already {payment.status}.")
    if payment.provider_ref:
        raise Conflict("Online payments are reversed by issuing a refund, not by voiding.")
    payment.status = "void"
    payment.voided_at = _now()
    payment.void_reason = reason
    inv.amount_paid_cents -= payment.amount_cents
    settle_invoice_status(inv, shop_today(get_business(db)))
    audit.record(
        db,
        user=user,
        action="payment.voided",
        entity_type="invoice",
        entity_id=inv.id,
        details={
            "payment_id": payment.id,
            "amount_cents": payment.amount_cents,
            "reason": reason,
            "balance_cents": inv.balance_cents,
        },
    )
    return payment
