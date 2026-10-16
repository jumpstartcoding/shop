"""Email templates and sending, with a log row for every attempt.

Sending never raises into a workflow. A failed email is recorded and reported to the
mechanic; the estimate, invoice, or payment it was about stays saved.
"""

import re
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.email import Attachment, EmailError, OutgoingEmail, send_email
from app.models import EmailLog, EmailTemplate
from app.services.business import get_business

log = structlog.get_logger()

# Built-in wording. The shop can edit any of these in Settings; edits are stored in
# email_templates and these remain the fallback.
DEFAULTS: dict[str, tuple[str, str, str]] = {
    # key: (label, subject, body)
    "appointment_confirmed": (
        "Appointment confirmation",
        "Your appointment with {shop_name} is confirmed",
        "Hi {customer_first_name},\n\nYour appointment has been confirmed for {appointment_time}"
        " for your {vehicle}.\n\nIf you need to change it, call us at {shop_phone}.\n\n{shop_name}",
    ),
    "estimate_ready": (
        "Estimate ready",
        "Your repair estimate {document_number} from {shop_name}",
        "Hi {customer_first_name},\n\nYour repair estimate for your {vehicle} is ready for review."
        "\n\nEstimated total: {total}\n\nReview, approve, or ask a question here:\n{link}\n\n"
        "Questions? Call us at {shop_phone}.\n\n{shop_name}",
    ),
    "work_authorization": (
        "Repair authorization request",
        "Please authorize work on your {vehicle}",
        "Hi {customer_first_name},\n\nPlease review and authorize the work for your {vehicle}:"
        "\n{link}\n\nQuestions? Call us at {shop_phone}.\n\n{shop_name}",
    ),
    "inspection_ready": (
        "Inspection report",
        "Your {vehicle} inspection report from {shop_name}",
        "Hi {customer_first_name},\n\nWe've finished inspecting your {vehicle}. Your report, "
        "with photos of anything we found, is here:\n{link}\n\nItems in red need attention "
        "soon; yellow ones are worth watching. Questions? Reply on that page or call us at "
        "{shop_phone}.\n\n{shop_name}",
    ),
    "estimate_approved": (
        "Thanks for approving",
        "Thanks for approving estimate {document_number}",
        "Hi {customer_first_name},\n\nThank you for approving your repair estimate. We'll get "
        "started and let you know when your {vehicle} is ready.\n\nYour signed copy:\n{link}\n\n"
        "{shop_name}",
    ),
    "vehicle_ready": (
        "Vehicle ready",
        "Your {vehicle} is ready for pickup",
        "Hi {customer_first_name},\n\nYour vehicle is ready for pickup.\n\nOur hours and address "
        "are on our website, or call us at {shop_phone}.\n\n{shop_name}",
    ),
    "invoice_ready": (
        "Invoice",
        "Invoice {document_number} from {shop_name}",
        "Hi {customer_first_name},\n\nYour repair invoice for your {vehicle} is ready.\n\n"
        "Amount due: {balance}\n\nView or download it here:\n{link}\n\n{shop_name}",
    ),
    "payment_receipt": (
        "Payment receipt",
        "Receipt for your payment to {shop_name}",
        "Hi {customer_first_name},\n\nWe received your payment of {amount} for invoice "
        "{document_number}. Your receipt is attached.\n\nRemaining balance: {balance}\n\n"
        "Thank you,\n{shop_name}",
    ),
    "service_reminder": (
        "Service reminder",
        "Your {vehicle} may be due for service",
        "Hi {customer_first_name},\n\nYour {vehicle} may be due for {service}.\n\nBook online or "
        "call us at {shop_phone}.\n\n{shop_name}",
    ),
}

PLACEHOLDERS = (
    "customer_first_name",
    "customer_name",
    "shop_name",
    "shop_phone",
    "vehicle",
    "document_number",
    "total",
    "balance",
    "amount",
    "link",
    "appointment_time",
    "service",
)
_TOKEN = re.compile(r"\{([a-z_]+)\}")


def fill(text: str, ctx: dict[str, str | None]) -> str:
    """Replace known {placeholders}; leave anything else exactly as written."""
    return _TOKEN.sub(
        lambda m: str(ctx.get(m.group(1)) or "") if m.group(1) in PLACEHOLDERS else m.group(0), text
    )


def get_template(db: Session, key: str) -> tuple[str, str]:
    row = db.scalar(select(EmailTemplate).where(EmailTemplate.key == key))
    if row:
        return row.subject, row.body
    _, subject, body = DEFAULTS[key]
    return subject, body


@dataclass
class EmailResult:
    status: str  # sent | failed | skipped
    to: str | None
    message: str

    def as_dict(self) -> dict:
        return {"status": self.status, "to": self.to, "message": self.message}


def send_templated(
    db: Session,
    key: str,
    to: str | None,
    ctx: dict[str, str | None],
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    attachments: list[Attachment] | None = None,
) -> EmailResult:
    business = get_business(db)
    base = {"shop_name": business.name, "shop_phone": business.phone}
    subject_t, body_t = get_template(db, key)
    full = {**base, **ctx}
    subject = fill(subject_t, full)[:200]
    if not to:
        db.add(
            EmailLog(
                template_key=key,
                to_address=None,
                subject=subject,
                status="skipped",
                entity_type=entity_type,
                entity_id=entity_id,
                error="No email address on file.",
            )
        )
        return EmailResult("skipped", None, "No email address on file, so nothing was emailed.")
    try:
        mid = send_email(
            OutgoingEmail(
                to=to,
                subject=subject,
                text=fill(body_t, full),
                reply_to=business.email,
                from_name=business.name,
                attachments=attachments or [],
            )
        )
    except EmailError as exc:
        log.warning("email_failed", key=key, error=str(exc)[:200])
        db.add(
            EmailLog(
                template_key=key,
                to_address=to,
                subject=subject,
                status="failed",
                entity_type=entity_type,
                entity_id=entity_id,
                error=str(exc)[:500],
            )
        )
        return EmailResult("failed", to, f"The email to {to} couldn't be sent.")
    db.add(
        EmailLog(
            template_key=key,
            to_address=to,
            subject=subject,
            status="sent",
            entity_type=entity_type,
            entity_id=entity_id,
            provider_message_id=mid,
        )
    )
    return EmailResult("sent", to, f"Emailed to {to}.")


def notify_shop(db: Session, subject: str, text: str) -> None:
    """Heads-up to the shop's own inbox about something that came in from a customer."""
    business = get_business(db)
    if not (business.notify_by_email and business.email):
        return
    try:
        send_email(OutgoingEmail(to=business.email, subject=subject[:200], text=text))
        db.add(
            EmailLog(
                template_key="shop_notice",
                to_address=business.email,
                subject=subject[:200],
                status="sent",
            )
        )
    except EmailError as exc:
        db.add(
            EmailLog(
                template_key="shop_notice",
                to_address=business.email,
                subject=subject[:200],
                status="failed",
                error=str(exc)[:500],
            )
        )
