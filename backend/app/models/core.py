"""Users, sessions, shop settings, services catalog, audit log, document numbering."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ArchiveMixin, Base, IdMixin, TimestampMixin

USER_ROLES = ("owner", "office", "tech")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {USER_ROLES}", name="role"),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()


class Business(IdMixin, TimestampMixin, Base):
    """Shop profile and pricing defaults. Exactly one row in V1."""

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(254))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    service_area: Mapped[str | None] = mapped_column(Text)
    logo_key: Mapped[str | None] = mapped_column(String(300))
    # {"mon": {"open": "08:00", "close": "17:00"} | null, ...}
    hours: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    about_text: Mapped[str | None] = mapped_column(Text)
    certifications: Mapped[str | None] = mapped_column(Text)
    offers_towing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    towing_info: Mapped[str | None] = mapped_column(Text)
    financing_info: Mapped[str | None] = mapped_column(Text)
    social_links: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/New_York")
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal("0"))
    tax_labor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tax_parts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tax_fees: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_labor_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    default_parts_markup_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False, default=Decimal("0")
    )
    invoice_prefix: Mapped[str] = mapped_column(String(10), nullable=False, default="INV")
    estimate_prefix: Mapped[str] = mapped_column(String(10), nullable=False, default="EST")
    work_order_prefix: Mapped[str] = mapped_column(String(10), nullable=False, default="WO")
    invoice_due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimate_valid_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    authorization_statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "By signing below, I authorize the work described in this document "
            "and acknowledge the estimated charges shown."
        ),
    )
    allow_typed_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    invoice_footer: Mapped[str | None] = mapped_column(Text)
    # Printed on signed work order authorizations (e.g. storage fees, diagnostic charges).
    terms_text: Mapped[str | None] = mapped_column(Text)
    # Email the shop when a booking request, question, or customer approval comes in.
    notify_by_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Real customer reviews the shop chooses to show: [{"name": ..., "text": ...}].
    testimonials: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reviews_url: Mapped[str | None] = mapped_column(String(300))


class Service(IdMixin, TimestampMixin, ArchiveMixin, Base):
    """A service listed on the public website. Editable from the admin dashboard."""

    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    starting_price_cents: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditLog(IdMixin, Base):
    """Append-only record of important actions."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # NULL actor means the customer (via a link) or the system (webhook, scheduled job).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(40), nullable=False)  # user | customer | system
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))


class DocumentCounter(Base):
    """Last issued sequence number per document kind and year (gap-free numbering)."""

    __tablename__ = "document_counters"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
