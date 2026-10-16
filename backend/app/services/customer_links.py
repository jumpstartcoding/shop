"""What a customer can see and do through a link. No sign-in; the link is the credential,
scoped to one document and one set of actions."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.errors import AppError, Conflict, NotFound
from app.core.storage import get_storage
from app.documents.snapshot import snapshot_invoice
from app.models import (
    AccessToken,
    Customer,
    DocumentVersion,
    Estimate,
    Inquiry,
    Inspection,
    Invoice,
    Photo,
    WorkOrder,
)
from app.schemas.public import QuestionIn, RespondIn
from app.services import documents, notify
from app.services.business import get_business
from app.services.payments import online_payments_available
from app.services.photos import photo_ids_in
from app.services.workflow import apply_estimate_decision

RESPONDABLE = {"sent", "viewed"}


def _version(db: Session, link: AccessToken) -> DocumentVersion:
    v = db.get(DocumentVersion, link.document_version_id) if link.document_version_id else None
    if v is None:
        raise NotFound("This document isn't available.")
    return v


def view(db: Session, token: str) -> dict:
    link = documents.resolve_link(db, token, touch=True)
    business = get_business(db)
    shop = {"name": business.name, "phone": business.phone, "email": business.email}

    if link.purpose == "invoice":
        inv = documents.invoice_link_entity(db, link)
        if inv.status == "void":
            raise documents.LinkGone(
                "This invoice has been voided. Contact the shop with any questions."
            )
        if inv.sent_at and inv.viewed_at is None:
            inv.viewed_at = datetime.now(UTC)
            if inv.status == "sent":
                inv.status = "viewed"
        return {
            "purpose": "invoice",
            "shop": shop,
            "document": snapshot_invoice(db, inv),
            "state": {
                "status": inv.status,
                "balance_cents": inv.balance_cents,
                "can_pay_online": inv.balance_cents > 0 and online_payments_available(db),
                "min_online_cents": min(get_settings().min_online_payment_cents, inv.balance_cents),
            },
            "receipts": [
                {"id": p.id, "amount_cents": p.amount_cents, "paid_at": p.paid_at}
                for p in inv.payments
                if p.status == "succeeded"
            ],
        }

    version = _version(db, link)
    auth = documents.latest_authorization(db, version.entity_type, version.entity_id)
    signed_this = auth is not None and auth.document_version_id == version.id
    can_respond = not signed_this
    if link.purpose == "estimate":
        est = db.get(Estimate, link.entity_id)
        if est is None:
            raise NotFound("This estimate no longer exists.")
        can_respond = can_respond and est.status in RESPONDABLE and est.version == version.version
        if est.status == "sent" and est.version == version.version:
            est.status = "viewed"
            est.viewed_at = datetime.now(UTC)
            audit.record(
                db,
                actor="customer",
                action="estimate.viewed",
                entity_type="estimate",
                entity_id=est.id,
                details={"version": est.version},
            )
    return {
        "purpose": link.purpose,
        "shop": shop,
        "document": _without_storage_keys(version.content),
        "state": {
            "can_respond": can_respond,
            "decision": auth.decision if signed_this else None,
            "signed_at": auth.signed_at if signed_this else None,
            "signer_name": auth.signer_name if signed_this else None,
            "allow_typed_signature": business.allow_typed_signature,
            "authorization_statement": version.content.get("authorization_statement"),
            "content_sha256": version.content_sha256,
        },
    }


def _without_storage_keys(value):
    """Photo storage paths stay server-side; the page loads photos by id through the link."""
    if isinstance(value, dict):
        return {
            k: _without_storage_keys(v)
            for k, v in value.items()
            if k not in ("key", "thumb_key", "logo_key")
        }
    if isinstance(value, list):
        return [_without_storage_keys(v) for v in value]
    return value


def respond(
    db: Session, token: str, data: RespondIn, *, ip: str | None, user_agent: str | None
) -> dict:
    link = documents.resolve_link(db, token)
    if link.purpose not in ("estimate", "work_order", "inspection"):
        raise NotFound("There's nothing to sign on this link.")
    version = _version(db, link)
    auth = documents.latest_authorization(db, version.entity_type, version.entity_id)
    if auth is not None and auth.document_version_id == version.id:
        raise Conflict(
            "You've already responded to this document. Thank you.", code="already_signed"
        )

    business = get_business(db)
    est = None
    if link.purpose == "estimate":
        est = db.scalar(select(Estimate).where(Estimate.id == link.entity_id).with_for_update())
        if est is None or est.status not in RESPONDABLE or est.version != version.version:
            raise Conflict(
                "This estimate has changed since this link was sent. Ask the shop for the latest version.",
                code="stale_version",
            )
    elif link.purpose == "inspection":
        if data.decision != "approved":
            raise AppError(
                "An inspection report can only be acknowledged. Use 'Ask a question' if "
                "something doesn't look right.",
                status_code=422,
                code="validation_error",
            )
        if db.get(Inspection, link.entity_id) is None:
            raise NotFound("This inspection report no longer exists.")
    else:
        wo = db.get(WorkOrder, link.entity_id)
        if wo is None or wo.status in ("completed", "cancelled"):
            raise Conflict("This work order is closed. Contact the shop with any questions.")

    signature_key = typed_name = None
    method = "drawn"
    if data.decision == "approved":
        if not data.agree:
            raise AppError(
                "Check the box to confirm."
                if link.purpose == "inspection"
                else "Check the box to confirm you authorize the work.",
                status_code=422,
                code="validation_error",
            )
        if data.signature_image:
            signature_key = documents.save_signature_image(data.signature_image)
        elif data.typed_signature:
            if not business.allow_typed_signature:
                raise AppError(
                    "Please draw your signature.", status_code=422, code="validation_error"
                )
            method, typed_name = "typed", data.typed_signature
        else:
            raise AppError(
                "Please sign before submitting.", status_code=422, code="validation_error"
            )
    else:
        method = "link"  # a decline needs no signature

    customer = db.get(Customer, link.customer_id)
    a = documents.record_authorization(
        db,
        version=version,
        decision=data.decision,
        method=method,
        signer_name=data.signer_name,
        signer_email=customer.email if customer else None,
        signer_phone=customer.phone if customer else None,
        statement=version.content.get("authorization_statement")
        if data.decision == "approved"
        else None,
        signature_key=signature_key,
        typed_name=typed_name,
        note=data.note,
        ip=ip,
        user_agent=user_agent,
    )
    if est is not None:
        apply_estimate_decision(db, est, data.decision, "link", data.note)

    label = {
        "estimate": "estimate",
        "work_order": "repair authorization",
        "inspection": "inspection report",
    }[link.purpose]
    verb = "acknowledged" if link.purpose == "inspection" else data.decision
    notify.notify_shop(
        db,
        f"{data.signer_name} {verb} {label} {version.number}",
        f"{data.signer_name} {verb} {label} {version.number} (version {version.version})."
        + (f"\n\nNote: {data.note}" if data.note else "")
        + "\n\nOpen the shop dashboard to continue.",
    )
    if data.decision == "approved" and customer and customer.email and link.purpose != "inspection":
        notify.send_templated(
            db,
            "estimate_approved",
            customer.email,
            {
                "customer_first_name": customer.first_name,
                "customer_name": customer.full_name,
                "vehicle": version.content["vehicle"]["description"],
                "document_number": version.number,
                "link": f"{get_settings().public_base_url.rstrip('/')}/d/{token}",
            },
            entity_type=version.entity_type,
            entity_id=version.entity_id,
        )
    return {"decision": a.decision, "signed_at": a.signed_at}


def ask_question(db: Session, token: str, data: QuestionIn, *, ip: str | None) -> None:
    link = documents.resolve_link(db, token)
    customer = db.get(Customer, link.customer_id)
    number = None
    if link.document_version_id:
        number = _version(db, link).number
    elif link.purpose == "invoice":
        number = db.get(Invoice, link.entity_id).number
    db.add(
        Inquiry(
            kind="question",
            name=customer.full_name if customer else None,
            email=customer.email if customer else None,
            phone=customer.phone if customer else None,
            message=data.message,
            customer_id=link.customer_id,
            entity_type=link.purpose,
            entity_id=link.entity_id,
            ip_address=ip,
        )
    )
    audit.record(
        db,
        actor="customer",
        action=f"{link.purpose}.question",
        entity_type=link.purpose,
        entity_id=link.entity_id,
        ip_address=ip,
    )
    notify.notify_shop(
        db,
        f"Question about {number or link.purpose}",
        f"{customer.full_name if customer else 'A customer'} asked:\n\n{data.message}",
    )


def pdf_for_link(db: Session, token: str) -> tuple[bytes, str]:
    link = documents.resolve_link(db, token)
    if link.purpose == "invoice":
        from app.documents.render import render_pdf

        inv = documents.invoice_link_entity(db, link)
        return render_pdf(snapshot_invoice(db, inv)), f"{inv.number}.pdf"
    version = _version(db, link)
    auth = documents.latest_authorization(db, version.entity_type, version.entity_id)
    if auth and auth.document_version_id == version.id and auth.signed_version_id:
        signed = db.get(DocumentVersion, auth.signed_version_id)
        return documents.get_pdf(signed), f"{version.number}-signed.pdf"
    return documents.get_pdf(version), f"{version.number}.pdf"


def photo_for_link(db: Session, token: str, photo_id: int, size: str) -> bytes:
    """A photo, only if it appears on the document this link shows and hasn't been removed."""
    link = documents.resolve_link(db, token)
    if not link.document_version_id:
        raise NotFound("Photo not found.")
    version = _version(db, link)
    photo = db.get(Photo, photo_id)
    if (
        photo is None
        or photo.deleted_at is not None
        or photo.customer_id != link.customer_id
        or photo_id not in photo_ids_in(version.content)
    ):
        raise NotFound("Photo not found.")
    return get_storage().get(photo.thumb_key if size == "thumb" else photo.key)
