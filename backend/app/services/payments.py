"""Online payments and refunds.

How a card payment flows:
1. The customer opens their invoice link and chooses an amount (full balance or less).
2. We create a Stripe Checkout Session and send them to Stripe's page. Nothing is recorded yet.
3. Stripe sends a signed webhook when the payment succeeds. That webhook is the only thing
   that records an online payment. The "thanks" page the customer returns to only waits for it.
4. The event id is stored in the same transaction as the payment, with the invoice row locked,
   so retries, replays, and concurrent deliveries can never record a payment twice.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.email import Attachment
from app.core.errors import AppError, Conflict
from app.core.payments import METADATA_SOURCE, PaymentsUnavailable, get_gateway
from app.documents.render import render_pdf
from app.documents.snapshot import snapshot_receipt
from app.models import Invoice, Payment, StripeEvent, User
from app.services import documents, notify
from app.services.business import get_business
from app.services.workflow import get_or_404, recompute_paid

log = structlog.get_logger()

# Work to do after the webhook's transaction commits (emails), so a mail outage can never
# roll back a recorded payment.
AfterCommit = list[Callable[[Session], None]]


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# ------------------------------------------------------------------ availability


def online_payments_available(db: Session) -> bool:
    return get_settings().stripe_configured and get_business(db).online_payments_enabled


def payment_settings(db: Session) -> dict:
    s = get_settings()
    return {
        "configured": s.stripe_configured,
        "mode": s.stripe_mode,
        "enabled": get_business(db).online_payments_enabled,
        "currency": s.currency,
        "min_cents": s.min_online_payment_cents,
    }


# ------------------------------------------------------------------ checkout


def start_checkout(db: Session, token: str, amount_cents: int) -> str:
    """Create a Stripe Checkout Session for part or all of an invoice's balance."""
    if not online_payments_available(db):
        raise PaymentsUnavailable("Online payment isn't available. Please call the shop to pay.")
    link = documents.resolve_link(db, token)
    if link.purpose != "invoice":
        raise Conflict("This link isn't for an invoice.")
    inv = db.scalar(select(Invoice).where(Invoice.id == link.entity_id).with_for_update())
    if inv is None or inv.status == "void":
        raise Conflict("This invoice is no longer payable. Contact the shop.")
    balance = inv.balance_cents
    if balance <= 0:
        raise Conflict("This invoice is already paid in full. Thank you!", code="already_paid")
    s = get_settings()
    minimum = min(s.min_online_payment_cents, balance)
    if amount_cents < minimum:
        raise AppError(
            f"The smallest online payment is {_money(minimum)}.",
            status_code=422,
            code="validation_error",
        )
    if amount_cents > balance:
        raise AppError(
            f"That's more than the {_money(balance)} balance.",
            status_code=422,
            code="validation_error",
        )

    base = s.public_base_url.rstrip("/")
    # Same invoice, amount, and balance within the same minute -> same session. Stops a double
    # tap from opening two payment pages; a later attempt gets a fresh one.
    bucket = int(datetime.now(UTC).timestamp() // 60)
    key = hashlib.sha256(f"{inv.id}:{amount_cents}:{balance}:{bucket}".encode()).hexdigest()
    session = get_gateway().create_checkout(
        amount_cents=amount_cents,
        currency=s.currency,
        description=f"{get_business(db).name} invoice {inv.number}",
        customer_email=inv.customer.email,
        metadata={
            "source": METADATA_SOURCE,
            "invoice_id": str(inv.id),
            "invoice_number": inv.number,
        },
        success_url=f"{base}/d/{token}?paid=1",
        cancel_url=f"{base}/d/{token}",
        idempotency_key=f"checkout-{key}",
    )
    audit.record(
        db,
        actor="customer",
        action="payment.checkout_started",
        entity_type="invoice",
        entity_id=inv.id,
        details={"amount_cents": amount_cents, "session": session.id},
    )
    return session.url


# ------------------------------------------------------------------ webhooks


def process_event(db: Session, event: dict) -> tuple[str, AfterCommit]:
    """Apply one verified Stripe event. Returns an outcome label and post-commit work.
    The caller commits; any exception rolls everything back, including the event record, so
    Stripe's retry gets a clean second chance."""
    claimed = db.execute(
        insert(StripeEvent)
        .values(event_id=event["id"], type=event["type"], outcome="processing")
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(StripeEvent.event_id)
    ).first()
    if claimed is None:
        return "duplicate", []

    handler = HANDLERS.get(event["type"])
    after: AfterCommit = []
    outcome = handler(db, event, after) if handler else "ignored"
    db.get(StripeEvent, event["id"]).outcome = outcome
    return outcome, after


def _later(after: AfterCommit, subject: str, text: str) -> None:
    after.append(lambda db2: notify.notify_shop(db2, subject, text))


def _ours(obj: dict) -> bool:
    return (obj.get("metadata") or {}).get("source") == METADATA_SOURCE


def _checkout_paid(db: Session, event: dict, after: AfterCommit) -> str:
    session = event["data"]["object"]
    if not _ours(session) or session.get("mode") != "payment":
        return "ignored_not_ours"
    if session.get("payment_status") != "paid":
        # Delayed methods (bank debits) finish later with async_payment_succeeded.
        return "awaiting_payment"
    intent = session.get("payment_intent")
    amount = session.get("amount_total")
    if not intent or not isinstance(amount, int) or amount <= 0:
        log.warning("stripe_session_missing_fields", session=session.get("id"))
        return "ignored_incomplete"
    try:
        invoice_id = int(session["metadata"]["invoice_id"])
    except (KeyError, TypeError, ValueError):
        return "ignored_no_invoice"

    inv = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if inv is None:
        log.error("stripe_payment_unknown_invoice", invoice_id=invoice_id, intent=intent)
        _later(
            after,
            "Online payment for an unknown invoice",
            f"Stripe payment {intent} referenced invoice id {invoice_id}, which "
            "doesn't exist. Check your Stripe dashboard; it may need a refund.",
        )
        return "unknown_invoice"
    if db.scalar(select(Payment.id).where(Payment.provider_ref == intent)):
        return "already_recorded"
    if (session.get("currency") or "").lower() != get_settings().currency:
        _later(
            after,
            f"Online payment in an unexpected currency for {inv.number}",
            f"Stripe payment {intent} was in {session.get('currency')}. "
            "It was not applied to the invoice. Check your Stripe dashboard.",
        )
        return "wrong_currency"

    paid_at = datetime.fromtimestamp(event.get("created") or datetime.now(UTC).timestamp(), UTC)
    payment = Payment(
        invoice_id=inv.id,
        amount_cents=amount,
        method="online",
        status="succeeded",
        paid_at=paid_at,
        reference="Card or wallet via Stripe",
        provider_ref=intent,
        provider_session_id=session.get("id"),
    )
    db.add(payment)
    was_void = inv.status == "void"
    recompute_paid(db, inv)
    audit.record(
        db,
        actor="customer",
        action="payment.received",
        entity_type="invoice",
        entity_id=inv.id,
        details={
            "payment_id": payment.id,
            "amount_cents": amount,
            "method": "online",
            "stripe_payment_intent": intent,
            "balance_cents": inv.balance_cents,
        },
    )

    problem = None
    if was_void:
        problem = f"Invoice {inv.number} is void but received {_money(amount)} online. Refund it from the invoice."
    elif inv.overpaid_cents:
        problem = (
            f"Invoice {inv.number} is overpaid by {_money(inv.overpaid_cents)} "
            "(two payments overlapped). Refund the difference from the invoice."
        )
    _later(
        after,
        f"{'ACTION NEEDED: ' if problem else ''}Online payment {_money(amount)} for {inv.number}",
        (problem + "\n\n" if problem else "")
        + f"{inv.customer.full_name} paid {_money(amount)} online. Balance now {_money(inv.balance_cents)}.",
    )

    to = inv.customer.email or (session.get("customer_details") or {}).get("email")
    payment_id = payment.id

    def send_receipt(db2: Session) -> None:
        p = db2.get(Payment, payment_id)
        snap = snapshot_receipt(db2, p)
        notify.send_templated(
            db2,
            "payment_receipt",
            to,
            {
                "customer_first_name": p.invoice.customer.first_name,
                "vehicle": p.invoice.vehicle.display_name,
                "document_number": p.invoice.number,
                "amount": _money(p.amount_cents),
                "balance": _money(snap["balance_cents"]),
            },
            entity_type="invoice",
            entity_id=p.invoice_id,
            attachments=[Attachment(f"receipt-{p.invoice.number}-{p.id}.pdf", render_pdf(snap))],
        )

    after.append(send_receipt)
    return "payment_recorded_needs_refund" if problem else "payment_recorded"


def _async_failed(db: Session, event: dict, after: AfterCommit) -> str:
    session = event["data"]["object"]
    if not _ours(session):
        return "ignored_not_ours"
    inv_id = (session.get("metadata") or {}).get("invoice_id")
    audit.record(
        db,
        actor="system",
        action="payment.failed",
        entity_type="invoice",
        entity_id=int(inv_id) if inv_id and inv_id.isdigit() else None,
        details={"session": session.get("id")},
    )
    return "payment_failed"


def _charge_refunded(db: Session, event: dict, after: AfterCommit) -> str:
    """Keeps refunds made in the Stripe dashboard in sync. Refunds made from the app are
    already recorded, so the same total arriving here changes nothing."""
    charge = event["data"]["object"]
    intent = charge.get("payment_intent")
    refunded = charge.get("amount_refunded")
    if not intent or not isinstance(refunded, int):
        return "ignored_incomplete"
    payment = db.scalar(select(Payment).where(Payment.provider_ref == intent))
    if payment is None:
        return "ignored_not_ours"
    inv = db.scalar(select(Invoice).where(Invoice.id == payment.invoice_id).with_for_update())
    db.refresh(payment, with_for_update=True)
    target = min(refunded, payment.amount_cents)
    if target <= payment.refunded_cents:
        return "refund_already_recorded"
    added = target - payment.refunded_cents
    _apply_refund(payment, target)
    recompute_paid(db, inv)
    audit.record(
        db,
        actor="system",
        action="payment.refunded",
        entity_type="invoice",
        entity_id=inv.id,
        details={
            "payment_id": payment.id,
            "refunded_cents": added,
            "source": "stripe_dashboard",
            "balance_cents": inv.balance_cents,
        },
    )
    return "refund_synced"


def _dispute(db: Session, event: dict, after: AfterCommit) -> str:
    dispute = event["data"]["object"]
    intent = dispute.get("payment_intent")
    payment = db.scalar(select(Payment).where(Payment.provider_ref == intent)) if intent else None
    if payment is None:
        return "ignored_not_ours"
    inv = payment.invoice
    audit.record(
        db,
        actor="system",
        action="payment.disputed",
        entity_type="invoice",
        entity_id=inv.id,
        details={
            "payment_id": payment.id,
            "amount_cents": dispute.get("amount"),
            "reason": dispute.get("reason"),
        },
    )
    _later(
        after,
        f"ACTION NEEDED: card dispute on {inv.number}",
        f"{inv.customer.full_name} disputed a {_money(payment.amount_cents)} payment "
        f"(reason: {dispute.get('reason') or 'not given'}). Respond in your Stripe dashboard "
        "before the deadline. Stripe charges a dispute fee.",
    )
    return "dispute_noted"


HANDLERS = {
    "checkout.session.completed": _checkout_paid,
    "checkout.session.async_payment_succeeded": _checkout_paid,
    "checkout.session.async_payment_failed": _async_failed,
    "charge.refunded": _charge_refunded,
    "charge.dispute.created": _dispute,
}


# ------------------------------------------------------------------ refunds


def _apply_refund(payment: Payment, new_refunded_total: int) -> None:
    payment.refunded_cents = new_refunded_total
    payment.refunded_at = datetime.now(UTC)
    if payment.refunded_cents >= payment.amount_cents:
        payment.status = "refunded"


def refund_payment(
    db: Session, user: User, payment_id: int, amount_cents: int, reason: str
) -> Payment:
    payment = get_or_404(db, Payment, payment_id, "Payment")
    inv = db.scalar(select(Invoice).where(Invoice.id == payment.invoice_id).with_for_update())
    db.refresh(payment, with_for_update=True)
    if payment.status != "succeeded":
        raise Conflict(f"This payment is {payment.status}; there's nothing left to refund.")
    available = payment.amount_cents - payment.refunded_cents
    if amount_cents > available:
        raise Conflict(
            f"Only {_money(available)} of this payment can still be refunded.",
            code="refund_too_large",
        )

    refund_id = None
    if payment.provider_ref:
        # Call Stripe first. If it fails nothing here has changed, and the error says so.
        refund_id = get_gateway().refund(
            payment_intent=payment.provider_ref,
            amount_cents=amount_cents,
            idempotency_key=f"refund-{payment.id}-{payment.refunded_cents}-{amount_cents}",
            reason_note=reason,
        )
    _apply_refund(payment, payment.refunded_cents + amount_cents)
    recompute_paid(db, inv)
    audit.record(
        db,
        user=user,
        action="payment.refunded",
        entity_type="invoice",
        entity_id=inv.id,
        details={
            "payment_id": payment.id,
            "refunded_cents": amount_cents,
            "reason": reason,
            "via": "stripe" if refund_id else "manual",
            "stripe_refund": refund_id,
            "balance_cents": inv.balance_cents,
        },
    )
    return payment
