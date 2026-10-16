"""Admin side of documents: send links, PDFs, signed copies, email templates, inquiries."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.deps import require_user
from app.core.email import Attachment
from app.core.errors import AppError, Conflict, NotFound
from app.core.images import clean_png, decode_data_url
from app.core.storage import get_storage, new_key
from app.db import get_db
from app.documents.render import render_pdf
from app.documents.snapshot import (
    snapshot_estimate,
    snapshot_invoice,
    snapshot_receipt,
    snapshot_work_order,
)
from app.models import (
    AccessToken,
    Authorization,
    DocumentVersion,
    EmailLog,
    EmailTemplate,
    Estimate,
    Inquiry,
    Invoice,
    Payment,
    User,
    WorkOrder,
)
from app.routers.public import pdf_response
from app.schemas.common import _strip
from app.services import documents, notify, workflow
from app.services.business import get_business
from app.services.serialize import estimate_out, invoice_out

router = APIRouter(tags=["documents & messages"])


class SendIn(BaseModel):
    email: bool = True


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _ctx(doc, link: str | None = None) -> dict:
    c = doc.customer
    return {
        "customer_first_name": c.first_name,
        "customer_name": c.full_name,
        "vehicle": doc.vehicle.display_name,
        "document_number": doc.number,
        "total": _money(doc.total_cents),
        "link": link,
    }


# ------------------------------------------------------------------ sending


@router.post("/estimates/{est_id}/send")
def send_estimate(
    est_id: int, data: SendIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Lock the estimate as this version, create the customer's link, and email it.
    Sending again re-sends the same version with a fresh link."""
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate", lock=True)
    if est.status == "draft":
        workflow.mark_estimate_sent(db, user, est, channel="link")
    elif est.status not in ("sent", "viewed"):
        raise Conflict(
            f"Estimate {est.number} is {est.status}. Create a new version to send it again."
        )
    version = documents.issue_version(db, user, est)
    url = documents.create_link(
        db,
        user,
        purpose="estimate",
        entity=est,
        version=version,
        days=get_settings().estimate_link_days,
    )
    db.commit()  # the estimate is sent and the link works, whatever happens with email
    email = None
    if data.email:
        email = notify.send_templated(
            db,
            "estimate_ready",
            est.customer.email,
            _ctx(est, url),
            entity_type="estimate",
            entity_id=est.id,
        ).as_dict()
    return {"link": url, "email": email, "estimate": estimate_out(est, db)}


@router.post("/work-orders/{wo_id}/send-authorization")
def send_wo_authorization(
    wo_id: int, data: SendIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Ask the customer to sign the work order as written (drop-off authorization)."""
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order", lock=True)
    workflow.ensure_work_order_editable(wo)
    version = documents.issue_version(db, user, wo)
    url = documents.create_link(
        db,
        user,
        purpose="work_order",
        entity=wo,
        version=version,
        days=get_settings().estimate_link_days,
    )
    db.commit()
    email = None
    if data.email:
        email = notify.send_templated(
            db,
            "work_authorization",
            wo.customer.email,
            _ctx(wo, url),
            entity_type="work_order",
            entity_id=wo.id,
        ).as_dict()
    return {"link": url, "email": email, "version": version.version}


@router.post("/invoices/{inv_id}/send")
def send_invoice(
    inv_id: int, data: SendIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    inv = workflow.get_or_404(db, Invoice, inv_id, "Invoice", lock=True)
    if inv.status == "void":
        raise Conflict(f"Invoice {inv.number} is void.")
    workflow.mark_invoice_sent(db, user, inv)
    version = documents.issue_version(db, user, inv)
    url = documents.create_link(
        db,
        user,
        purpose="invoice",
        entity=inv,
        version=version,
        days=get_settings().invoice_link_days,
    )
    db.commit()
    email = None
    if data.email:
        email = notify.send_templated(
            db,
            "invoice_ready",
            inv.customer.email,
            {**_ctx(inv, url), "balance": _money(inv.balance_cents)},
            entity_type="invoice",
            entity_id=inv.id,
        ).as_dict()
    db.refresh(inv)
    return {"link": url, "email": email, "invoice": invoice_out(inv)}


@router.post("/payments/{payment_id}/email-receipt")
def email_receipt(payment_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    p = workflow.get_or_404(db, Payment, payment_id, "Payment")
    if p.status != "succeeded":
        raise Conflict("Only a completed payment has a receipt to send.")
    inv = p.invoice
    pdf = render_pdf(snapshot_receipt(db, p))
    result = notify.send_templated(
        db,
        "payment_receipt",
        inv.customer.email,
        {
            **_ctx(inv),
            "amount": _money(p.amount_cents),
            "balance": _money(snapshot_receipt(db, p)["balance_cents"]),
        },
        entity_type="invoice",
        entity_id=inv.id,
        attachments=[Attachment(f"receipt-{inv.number}-{p.id}.pdf", pdf)],
    )
    return {"email": result.as_dict()}


# ------------------------------------------------------------------ PDFs


@router.get("/estimates/{est_id}/pdf")
def estimate_pdf(est_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    est = workflow.get_or_404(db, Estimate, est_id, "Estimate")
    return pdf_response(render_pdf(snapshot_estimate(db, est)), f"{est.number}.pdf")


@router.get("/work-orders/{wo_id}/pdf")
def work_order_pdf(wo_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    wo = workflow.get_or_404(db, WorkOrder, wo_id, "Work order")
    return pdf_response(render_pdf(snapshot_work_order(db, wo, 0)), f"{wo.number}.pdf")


@router.get("/invoices/{inv_id}/pdf")
def invoice_pdf(inv_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    inv = workflow.get_or_404(db, Invoice, inv_id, "Invoice")
    return pdf_response(render_pdf(snapshot_invoice(db, inv)), f"{inv.number}.pdf")


@router.get("/payments/{payment_id}/receipt")
def receipt_pdf(payment_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    p = workflow.get_or_404(db, Payment, payment_id, "Payment")
    return pdf_response(render_pdf(snapshot_receipt(db, p)), f"receipt-{p.id}.pdf")


@router.get("/documents/{version_id}/pdf")
def version_pdf(version_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    v = workflow.get_or_404(db, DocumentVersion, version_id, "Document")
    suffix = "-signed" if v.kind == "signed" else ""
    return pdf_response(documents.get_pdf(v), f"{v.number}-v{v.version}{suffix}.pdf")


# ------------------------------------------------------------------ document trail


@router.get("/documents")
def document_trail(
    entity_type: str, entity_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    """Everything sent, signed, and emailed for one estimate, work order, invoice, or
    inspection report."""
    if entity_type not in ("estimate", "work_order", "invoice", "inspection"):
        raise AppError("Unknown document type.", status_code=422, code="validation_error")
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.entity_type == entity_type, DocumentVersion.entity_id == entity_id)
        .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
    )
    auths = db.scalars(
        select(Authorization)
        .where(Authorization.entity_type == entity_type, Authorization.entity_id == entity_id)
        .order_by(Authorization.signed_at.desc())
    )
    links = db.scalars(
        select(AccessToken)
        .where(AccessToken.purpose == entity_type, AccessToken.entity_id == entity_id)
        .order_by(AccessToken.created_at.desc())
    )
    emails = db.scalars(
        select(EmailLog)
        .where(EmailLog.entity_type == entity_type, EmailLog.entity_id == entity_id)
        .order_by(EmailLog.created_at.desc())
    )
    now = datetime.now(UTC)
    return {
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "kind": v.kind,
                "created_at": v.created_at,
                "content_sha256": v.content_sha256,
                "pdf_sha256": v.pdf_sha256,
            }
            for v in versions
        ],
        "authorizations": [
            {
                "id": a.id,
                "decision": a.decision,
                "method": a.method,
                "status": a.status,
                "signer_name": a.signer_name,
                "signed_at": a.signed_at,
                "ip_address": a.ip_address,
                "note": a.note,
                "version_id": a.document_version_id,
                "signed_version_id": a.signed_version_id,
                "recorded_by_shop": a.recorded_by_user_id is not None,
            }
            for a in auths
        ],
        "links": [
            {
                "id": t.id,
                "created_at": t.created_at,
                "expires_at": t.expires_at,
                "active": t.revoked_at is None and t.expires_at > now,
                "first_viewed_at": t.first_viewed_at,
                "view_count": t.view_count,
            }
            for t in links
        ],
        "emails": [
            {
                "id": e.id,
                "created_at": e.created_at,
                "status": e.status,
                "to": e.to_address,
                "subject": e.subject,
                "error": e.error,
            }
            for e in emails
        ],
    }


@router.post("/links/{link_id}/revoke", status_code=204)
def revoke_link(link_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    t = workflow.get_or_404(db, AccessToken, link_id, "Link")
    if t.revoked_at is None:
        t.revoked_at = datetime.now(UTC)
        audit.record(
            db, user=user, action="link.revoked", entity_type=t.purpose, entity_id=t.entity_id
        )


# ------------------------------------------------------------------ email templates


class TemplateIn(BaseModel):
    subject: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=200)]
    body: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=5000)]


@router.get("/email-templates")
def list_templates(db: Session = Depends(get_db), _: User = Depends(require_user)):
    edited = {t.key: t for t in db.scalars(select(EmailTemplate))}
    return {
        "placeholders": list(notify.PLACEHOLDERS),
        "templates": [
            {
                "key": key,
                "label": label,
                "subject": edited[key].subject if key in edited else subject,
                "body": edited[key].body if key in edited else body,
                "edited": key in edited,
                "default_subject": subject,
                "default_body": body,
            }
            for key, (label, subject, body) in notify.DEFAULTS.items()
        ],
    }


@router.put("/email-templates/{key}")
def save_template(
    key: str, data: TemplateIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    if key not in notify.DEFAULTS:
        raise NotFound("Unknown template.")
    row = db.scalar(select(EmailTemplate).where(EmailTemplate.key == key))
    if row is None:
        row = EmailTemplate(key=key, subject=data.subject, body=data.body)
        db.add(row)
    else:
        row.subject, row.body = data.subject, data.body
    audit.record(
        db,
        user=user,
        action="email_template.updated",
        entity_type="email_template",
        entity_id=None,
        details={"key": key},
    )
    return {"ok": True}


@router.delete("/email-templates/{key}", status_code=204)
def reset_template(key: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.scalar(select(EmailTemplate).where(EmailTemplate.key == key))
    if row:
        db.delete(row)
        audit.record(
            db,
            user=user,
            action="email_template.reset",
            entity_type="email_template",
            entity_id=None,
            details={"key": key},
        )


# ------------------------------------------------------------------ inquiries


@router.get("/inquiries")
def list_inquiries(
    include_handled: bool = False, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    stmt = select(Inquiry)
    if not include_handled:
        stmt = stmt.where(Inquiry.handled_at.is_(None))
    return [
        {
            "id": q.id,
            "kind": q.kind,
            "name": q.name,
            "email": q.email,
            "phone": q.phone,
            "message": q.message,
            "customer_id": q.customer_id,
            "entity_type": q.entity_type,
            "entity_id": q.entity_id,
            "created_at": q.created_at,
            "handled_at": q.handled_at,
        }
        for q in db.scalars(stmt.order_by(Inquiry.created_at.desc()).limit(200))
    ]


@router.post("/inquiries/{inquiry_id}/handled", status_code=204)
def mark_handled(
    inquiry_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    q = workflow.get_or_404(db, Inquiry, inquiry_id, "Message")
    q.handled_at = q.handled_at or datetime.now(UTC)


# ------------------------------------------------------------------ logo


class LogoIn(BaseModel):
    image: Annotated[str, Field(max_length=3_000_000)]


@router.post("/settings/logo")
def upload_logo(data: LogoIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    raw = decode_data_url(data.image, max_bytes=2_000_000, allow_jpeg=True)
    png = clean_png(raw, max_side=800, min_side=40)
    key = new_key("branding", "png")
    get_storage().put(key, png, "image/png")
    business = get_business(db)
    business.logo_key = key
    audit.record(
        db, user=user, action="settings.logo_updated", entity_type="business", entity_id=business.id
    )
    return {"ok": True}


@router.delete("/settings/logo", status_code=204)
def remove_logo(db: Session = Depends(get_db), user: User = Depends(require_user)):
    business = get_business(db)
    business.logo_key = None
    audit.record(
        db, user=user, action="settings.logo_removed", entity_type="business", entity_id=business.id
    )
