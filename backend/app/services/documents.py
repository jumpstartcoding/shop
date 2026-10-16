"""Issued versions, customer links, and authorizations (signatures).

Rules:
- A version is an immutable snapshot plus its PDF, both fingerprinted with SHA-256.
- What a customer sees through a link, and what they sign, is that stored snapshot, never the
  live record, so later edits can't change what was approved.
- Changing an approved estimate means a new version; older authorizations become
  "superseded" and links to older versions stop working.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.errors import AppError, Conflict, NotFound
from app.core.images import BadImage, clean_png, decode_data_url, has_ink
from app.core.security import hash_token, new_token
from app.core.storage import get_storage, new_key
from app.documents.render import render_pdf, sha256, signature_block
from app.documents.snapshot import (
    content_hash,
    snapshot_estimate,
    snapshot_inspection,
    snapshot_invoice,
    snapshot_work_order,
)
from app.models import (
    AccessToken,
    Authorization,
    DocumentVersion,
    Estimate,
    Inspection,
    Invoice,
    User,
    WorkOrder,
)
from app.services.business import get_business


class LinkGone(AppError):
    status_code = 410
    code = "link_gone"


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ versions


def material_fingerprint(snapshot: dict) -> str:
    """Hash of the parts of a document that change what's being authorized: the work, the
    prices, the people and vehicle. Excludes the print date, so the same work on a different
    day isn't treated as a change."""
    keys = ("customer", "vehicle", "concern", "notes", "items", "totals", "findings")
    return content_hash({k: snapshot.get(k) for k in keys})


def _store_pdf(prefix: str, pdf: bytes) -> str:
    key = new_key(prefix, "pdf")
    get_storage().put(key, pdf, "application/pdf")
    return key


def _latest_issued(db: Session, entity_type: str, entity_id: int) -> DocumentVersion | None:
    return db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.entity_type == entity_type,
            DocumentVersion.entity_id == entity_id,
            DocumentVersion.kind == "issued",
        )
        .order_by(DocumentVersion.version.desc())
        .limit(1)
    )


_SNAPSHOTS = {
    "work_order": snapshot_work_order,
    "invoice": snapshot_invoice,
    "inspection": snapshot_inspection,
}


def _entity_type(entity) -> str:
    if isinstance(entity, WorkOrder):
        return "work_order"
    if isinstance(entity, Inspection):
        return "inspection"
    return "invoice"


def issue_version(db: Session, user: User | None, entity) -> DocumentVersion:
    """Snapshot and render the document as it stands now. Re-issuing unchanged content returns
    the existing version, so sending twice doesn't create two versions."""
    if isinstance(entity, Estimate):
        entity_type, version = "estimate", entity.version
        existing = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.entity_type == "estimate",
                DocumentVersion.entity_id == entity.id,
                DocumentVersion.version == version,
                DocumentVersion.kind == "issued",
            )
        )
        if existing:
            return existing
        snap = snapshot_estimate(db, entity)
    else:
        entity_type = _entity_type(entity)
        latest = _latest_issued(db, entity_type, entity.id)
        version = (latest.version + 1) if latest else 1
        snap = _SNAPSHOTS[entity_type](db, entity, version)
        if latest and material_fingerprint(latest.content) == material_fingerprint(snap):
            return latest

    pdf = render_pdf(snap)
    dv = DocumentVersion(
        entity_type=entity_type,
        entity_id=entity.id,
        version=version,
        kind="issued",
        number=entity.number,
        content=snap,
        content_sha256=content_hash(snap),
        pdf_key=_store_pdf(f"documents/{entity_type}", pdf),
        pdf_sha256=sha256(pdf),
        created_by_user_id=user.id if user else None,
    )
    db.add(dv)
    db.flush()
    audit.record(
        db,
        user=user,
        action=f"{entity_type}.version_issued",
        entity_type=entity_type,
        entity_id=entity.id,
        details={"version": version, "content_sha256": dv.content_sha256},
    )
    return dv


# ------------------------------------------------------------------ links


def create_link(
    db: Session,
    user: User | None,
    *,
    purpose: str,
    entity,
    version: DocumentVersion | None,
    days: int,
) -> str:
    """New customer link; earlier links for the same document stop working. Returns the URL."""
    now = _now()
    for old in db.scalars(
        select(AccessToken).where(
            AccessToken.purpose == purpose,
            AccessToken.entity_id == entity.id,
            AccessToken.revoked_at.is_(None),
        )
    ):
        old.revoked_at = now
    token = new_token()
    db.add(
        AccessToken(
            token_hash=hash_token(token),
            purpose=purpose,
            entity_id=entity.id,
            document_version_id=version.id if version else None,
            customer_id=entity.customer_id,
            expires_at=now + timedelta(days=days),
            created_by_user_id=user.id if user else None,
        )
    )
    db.flush()
    audit.record(
        db,
        user=user,
        action="link.created",
        entity_type=purpose,
        entity_id=entity.id,
        details={"expires_in_days": days},
    )
    return f"{get_settings().public_base_url.rstrip('/')}/d/{token}"


def revoke_links(db: Session, purpose: str, entity_id: int) -> int:
    now = _now()
    n = 0
    for t in db.scalars(
        select(AccessToken).where(
            AccessToken.purpose == purpose,
            AccessToken.entity_id == entity_id,
            AccessToken.revoked_at.is_(None),
        )
    ):
        t.revoked_at = now
        n += 1
    db.flush()
    return n


def resolve_link(db: Session, token: str, *, touch: bool = False) -> AccessToken:
    link = db.scalar(select(AccessToken).where(AccessToken.token_hash == hash_token(token)))
    if link is None:
        raise NotFound(
            "This link isn't valid. Check that it was copied completely, or contact the shop."
        )
    if link.revoked_at is not None:
        raise LinkGone(
            "This link has been replaced by a newer one. Use the most recent link from the shop."
        )
    if link.expires_at <= _now():
        raise LinkGone("This link has expired. Contact the shop for a new one.")
    if touch:
        now = _now()
        link.first_viewed_at = link.first_viewed_at or now
        link.last_viewed_at = now
        link.view_count += 1
    return link


# ------------------------------------------------------------------ authorizations


def latest_authorization(db: Session, entity_type: str, entity_id: int) -> Authorization | None:
    return db.scalar(
        select(Authorization)
        .where(
            Authorization.entity_type == entity_type,
            Authorization.entity_id == entity_id,
            Authorization.status == "valid",
        )
        .order_by(Authorization.signed_at.desc(), Authorization.id.desc())
        .limit(1)
    )


def supersede_authorizations(db: Session, entity_type: str, entity_id: int) -> int:
    n = 0
    for a in db.scalars(
        select(Authorization).where(
            Authorization.entity_type == entity_type,
            Authorization.entity_id == entity_id,
            Authorization.status == "valid",
        )
    ):
        a.status = "superseded"
        n += 1
    db.flush()
    return n


def save_signature_image(data_url: str) -> str:
    raw = decode_data_url(data_url, max_bytes=400_000)
    png = clean_png(raw, max_side=900, min_side=50, flatten_white=True)
    if not has_ink(png):
        raise BadImage("The signature box is empty. Sign with your finger or mouse, then submit.")
    key = new_key("signatures", "png")
    get_storage().put(key, png, "image/png")
    return key


def record_authorization(
    db: Session,
    *,
    version: DocumentVersion,
    decision: str,
    method: str,
    signer_name: str,
    signer_email: str | None,
    signer_phone: str | None,
    statement: str | None,
    signature_key: str | None = None,
    typed_name: str | None = None,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    user: User | None = None,
) -> Authorization:
    """Store the decision against the exact version shown, then render and store the signed
    PDF. The signed PDF is itself a new immutable version (kind 'signed')."""
    if version.kind != "issued":
        raise Conflict("Only an issued document can be authorized.")
    supersede_authorizations(db, version.entity_type, version.entity_id)
    auth = Authorization(
        document_version_id=version.id,
        entity_type=version.entity_type,
        entity_id=version.entity_id,
        decision=decision,
        method=method,
        status="valid",
        signer_name=signer_name,
        signer_email=signer_email,
        signer_phone=signer_phone,
        statement=statement,
        content_sha256=version.content_sha256,
        signature_key=signature_key,
        typed_name=typed_name,
        note=note,
        ip_address=ip,
        user_agent=(user_agent or "")[:300] or None,
        recorded_by_user_id=user.id if user else None,
        signed_at=_now(),
    )
    db.add(auth)
    db.flush()

    tz = ZoneInfo(get_business(db).timezone)
    image = get_storage().get(signature_key) if signature_key else None
    block = signature_block(auth, version.content_sha256, image)
    block["signed_at"] = auth.signed_at.astimezone(tz)
    pdf = render_pdf(version.content, block)
    signed = DocumentVersion(
        entity_type=version.entity_type,
        entity_id=version.entity_id,
        version=version.version,
        kind="signed",
        number=version.number,
        content=version.content,
        content_sha256=version.content_sha256,
        pdf_key=_store_pdf(f"signed/{version.entity_type}", pdf),
        pdf_sha256=sha256(pdf),
        parent_id=version.id,
        created_by_user_id=user.id if user else None,
    )
    db.add(signed)
    db.flush()
    auth.signed_version_id = signed.id
    audit.record(
        db,
        user=user,
        actor="user" if user else "customer",
        action=f"{version.entity_type}.{decision}",
        entity_type=version.entity_type,
        entity_id=version.entity_id,
        ip_address=ip,
        details={
            "version": version.version,
            "method": method,
            "authorization_id": auth.id,
            "content_sha256": version.content_sha256,
            "signed_pdf_sha256": signed.pdf_sha256,
        },
    )
    return auth


def authorization_state(db: Session, entity_type: str, entity) -> dict:
    """For the admin screens: is this document authorized, and has it changed since?"""
    auth = latest_authorization(db, entity_type, entity.id)
    pending = db.scalar(
        select(func.count())
        .select_from(AccessToken)
        .where(
            AccessToken.purpose == entity_type,
            AccessToken.entity_id == entity.id,
            AccessToken.revoked_at.is_(None),
            AccessToken.expires_at > _now(),
        )
    )
    if auth is None:
        return {
            "status": "awaiting" if pending else "none",
            "signed_at": None,
            "signer_name": None,
            "method": None,
            "authorization_id": None,
        }
    changed = False
    if entity_type in ("work_order", "inspection"):
        current = _SNAPSHOTS[entity_type](db, entity, 0)
        changed = material_fingerprint(current) != material_fingerprint(auth.version.content)
    status = auth.decision
    if changed:
        status = "changed_since_signed"
    return {
        "status": status,
        "signed_at": auth.signed_at,
        "signer_name": auth.signer_name,
        "method": auth.method,
        "authorization_id": auth.id,
    }


def get_pdf(version: DocumentVersion) -> bytes:
    data = get_storage().get(version.pdf_key)
    if sha256(data) != version.pdf_sha256:
        # Storage returned something other than what was signed; refuse rather than serve it.
        raise AppError(
            "This document failed its integrity check. Contact the shop.",
            status_code=500,
            code="integrity_error",
        )
    return data


def invoice_link_entity(db: Session, link: AccessToken) -> Invoice:
    inv = db.get(Invoice, link.entity_id)
    if inv is None:
        raise NotFound("This invoice no longer exists.")
    return inv
