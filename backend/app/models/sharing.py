"""Customer links, issued and signed document versions, authorizations, inquiries, email.

A document version is an immutable snapshot of exactly what the customer was shown, with a
SHA-256 of the content and of the rendered PDF. Authorizations point at the version they
approve, so a later edit can never change what someone signed.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin

DOC_ENTITY_TYPES = ("estimate", "work_order", "invoice", "receipt", "inspection")
VERSION_KINDS = ("issued", "signed")
DECISIONS = ("approved", "declined")
AUTH_METHODS = ("drawn", "typed", "link", "in_person", "phone", "email", "text")
LINK_PURPOSES = ("estimate", "work_order", "invoice", "inspection", "history")
INQUIRY_KINDS = ("contact", "question")


class DocumentVersion(IdMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(f"entity_type IN {DOC_ENTITY_TYPES}", name="entity_type"),
        CheckConstraint(f"kind IN {VERSION_KINDS}", name="kind"),
        UniqueConstraint("entity_type", "entity_id", "version", "kind", name="uq_doc_version"),
        Index("ix_document_versions_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_key: Mapped[str] = mapped_column(String(300), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Authorization(IdMixin, Base):
    __tablename__ = "authorizations"
    __table_args__ = (
        CheckConstraint(f"decision IN {DECISIONS}", name="decision"),
        CheckConstraint(f"method IN {AUTH_METHODS}", name="method"),
        CheckConstraint("status IN ('valid', 'superseded')", name="status"),
        Index("ix_authorizations_entity", "entity_type", "entity_id"),
    )

    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="valid")
    signer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    signer_email: Mapped[str | None] = mapped_column(String(254))
    signer_phone: Mapped[str | None] = mapped_column(String(40))
    statement: Mapped[str | None] = mapped_column(Text)  # exact wording shown at signing
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_key: Mapped[str | None] = mapped_column(String(300))
    typed_name: Mapped[str | None] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(String(1000))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    version: Mapped[DocumentVersion] = relationship(foreign_keys=[document_version_id])


class AccessToken(IdMixin, Base):
    """A customer link. Only the SHA-256 of the token is stored."""

    __tablename__ = "access_tokens"
    __table_args__ = (
        CheckConstraint(f"purpose IN {LINK_PURPOSES}", name="purpose"),
        Index("ix_access_tokens_entity", "purpose", "entity_id"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Inquiry(IdMixin, Base):
    """A contact-form message or a customer's question about an estimate."""

    __tablename__ = "inquiries"
    __table_args__ = (CheckConstraint(f"kind IN {INQUIRY_KINDS}", name="kind"),)

    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    ip_address: Mapped[str | None] = mapped_column(String(64), index=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class EmailTemplate(IdMixin, Base):
    """A shop's edited version of a built-in template. Absent rows use the built-in text."""

    __tablename__ = "email_templates"

    key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmailLog(IdMixin, Base):
    __tablename__ = "email_log"
    __table_args__ = (
        CheckConstraint("status IN ('sent', 'failed', 'skipped')", name="status"),
        Index("ix_email_log_entity", "entity_type", "entity_id"),
    )

    template_key: Mapped[str] = mapped_column(String(40), nullable=False)
    to_address: Mapped[str | None] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StripeEvent(Base):
    """Every Stripe event processed, keyed by Stripe's event id. Inserting here first, in the
    same transaction as the payment, makes webhook delivery idempotent: a retried or replayed
    event finds its id already present and changes nothing."""

    __tablename__ = "stripe_events"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(60), nullable=False, default="processed")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
