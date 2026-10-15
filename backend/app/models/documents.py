"""Work orders, estimates, invoices, their line items, and payments.

Line items are copied between documents (estimate -> work order -> invoice) rather than
shared, so an issued invoice never changes when a work order is edited later.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin
from app.models.customers import Customer, Vehicle

LINE_KINDS = ("labor", "part", "fee", "discount")

WORK_ORDER_STATUSES = (
    "new",
    "checked_in",
    "diagnosing",
    "waiting_approval",
    "approved",
    "in_repair",
    "quality_check",
    "ready_for_pickup",
    "completed",
    "cancelled",
)
ESTIMATE_STATUSES = ("draft", "sent", "viewed", "approved", "declined", "expired", "superseded")
INVOICE_STATUSES = ("draft", "sent", "viewed", "partially_paid", "paid", "overdue", "void")
PAYMENT_METHODS = ("cash", "check", "card", "online", "other")
PAYMENT_STATUSES = ("pending", "succeeded", "failed", "refunded", "void")

QC_CHECKLIST_KEYS = (
    "repair_completed",
    "vehicle_inspected",
    "test_drive_completed",
    "tools_removed",
    "old_parts_handled",
    "customer_notified",
    "invoice_generated",
    "payment_confirmed",
)


class LineItemMixin(IdMixin):
    """Columns shared by work order, estimate, and invoice lines."""

    @declared_attr.directive
    def __table_args__(cls):  # noqa: N805
        return (
            CheckConstraint(f"kind IN {LINE_KINDS}", name="kind"),
            CheckConstraint("quantity > 0", name="quantity_positive"),
            CheckConstraint("unit_price_cents >= 0", name="price_nonnegative"),
            CheckConstraint("line_total_cents >= 0", name="total_nonnegative"),
        )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("1"))
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Internal cost for parts. Never shown to customers.
    unit_cost_cents: Mapped[int | None] = mapped_column(Integer)
    markup_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    part_number: Mapped[str | None] = mapped_column(String(80))
    vendor_name: Mapped[str | None] = mapped_column(String(120))
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    warranty_miles: Mapped[int | None] = mapped_column(Integer)
    warranty_notes: Mapped[str | None] = mapped_column(String(300))


class TotalsMixin:
    """Stored totals, always produced by app.core.pricing.compute_totals."""

    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal("0"))
    labor_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parts_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fees_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    taxable_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkOrder(IdMixin, TimestampMixin, TotalsMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (CheckConstraint(f"status IN {WORK_ORDER_STATUSES}", name="status"),)

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    concern: Mapped[str | None] = mapped_column(Text)
    customer_notes: Mapped[str | None] = mapped_column(Text)  # shown on documents
    internal_notes: Mapped[str | None] = mapped_column(Text)  # never shown to customers
    mileage_in: Mapped[int | None] = mapped_column(Integer)
    mileage_out: Mapped[int | None] = mapped_column(Integer)
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qc_checklist: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship()
    vehicle: Mapped[Vehicle] = relationship()
    items: Mapped[list["WorkOrderItem"]] = relationship(
        back_populates="work_order",
        order_by="WorkOrderItem.position",
        cascade="all, delete-orphan",
    )


class WorkOrderItem(LineItemMixin, Base):
    __tablename__ = "work_order_items"

    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_order: Mapped[WorkOrder] = relationship(back_populates="items")


class Estimate(IdMixin, TimestampMixin, TotalsMixin, Base):
    __tablename__ = "estimates"
    __table_args__ = (CheckConstraint(f"status IN {ESTIMATE_STATUSES}", name="status"),)

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    concern: Mapped[str | None] = mapped_column(Text)
    customer_notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    mileage: Mapped[int | None] = mapped_column(Integer)
    expires_on: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the estimate is sent for authorization; editing requires a new version.
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How a decision recorded by the mechanic was given (in_person, phone, email, link).
    decision_method: Mapped[str | None] = mapped_column(String(20))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship()
    vehicle: Mapped[Vehicle] = relationship()
    items: Mapped[list["EstimateItem"]] = relationship(
        back_populates="estimate", order_by="EstimateItem.position", cascade="all, delete-orphan"
    )


class EstimateItem(LineItemMixin, Base):
    __tablename__ = "estimate_items"

    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estimate: Mapped[Estimate] = relationship(back_populates="items")


class Invoice(IdMixin, TimestampMixin, TotalsMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(f"status IN {INVOICE_STATUSES}", name="status"),
        CheckConstraint("amount_paid_cents >= 0", name="paid_nonnegative"),
    )

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    mileage: Mapped[int | None] = mapped_column(Integer)
    customer_notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    amount_paid_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(300))

    customer: Mapped[Customer] = relationship()
    vehicle: Mapped[Vehicle] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", order_by="InvoiceItem.position", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", order_by="Payment.paid_at"
    )

    @property
    def balance_cents(self) -> int:
        return max(self.total_cents - self.amount_paid_cents, 0)


class InvoiceItem(LineItemMixin, Base):
    __tablename__ = "invoice_items"

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(f"method IN {PAYMENT_METHODS}", name="method"),
        CheckConstraint(f"status IN {PAYMENT_STATUSES}", name="status"),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
    )

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="succeeded")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reference: Mapped[str | None] = mapped_column(String(120))  # check number, last 4, etc.
    # Stripe payment intent id for online payments; unique so a webhook can't double-record.
    provider_ref: Mapped[str | None] = mapped_column(String(120), unique=True)
    notes: Mapped[str | None] = mapped_column(String(500))
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(300))

    invoice: Mapped[Invoice] = relationship(back_populates="payments")
