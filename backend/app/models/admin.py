"""Shop administration: vendors, a simple parts list, expenses, maintenance reminders.

Deliberately small (spec §13): one stock count per part, no locations, bins, purchase
orders, or costing layers. A part's stock goes down when a work order using it is completed
and comes back if that work order is reopened.
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ArchiveMixin, Base, IdMixin, TimestampMixin

EXPENSE_CATEGORIES = (
    "parts",
    "tools",
    "rent",
    "utilities",
    "insurance",
    "advertising",
    "software",
    "supplies",
    "other",
)
REMINDER_KINDS = (
    "oil_change",
    "brake_inspection",
    "tire_rotation",
    "transmission_service",
    "coolant_service",
    "inspection",
    "custom",
)
REMINDER_STATUSES = ("open", "done", "dismissed")


class Vendor(IdMixin, TimestampMixin, ArchiveMixin, Base):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(300))
    account_number: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)


class Part(IdMixin, TimestampMixin, ArchiveMixin, Base):
    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint("cost_cents IS NULL OR cost_cents >= 0", name="cost_nonnegative"),
        CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="price_nonnegative"),
        CheckConstraint("reorder_at IS NULL OR reorder_at >= 0", name="reorder_nonnegative"),
        Index("ix_parts_part_number_lower", func.lower(text("part_number"))),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(60))
    vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), index=True
    )
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    # Customer price. Empty: the shop's default markup is applied to the cost.
    price_cents: Mapped[int | None] = mapped_column(Integer)
    # Empty: stock isn't tracked for this part (special-order items, fluids by the jug).
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 2))
    reorder_at: Mapped[float | None] = mapped_column(Numeric(10, 2))
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    warranty_miles: Mapped[int | None] = mapped_column(Integer)
    warranty_notes: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)

    vendor: Mapped[Vendor | None] = relationship()


class Expense(IdMixin, TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint(f"category IN {EXPENSE_CATEGORIES}", name="category"),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        Index("ix_expenses_date", "expense_date"),
    )

    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), index=True
    )
    vendor_name: Mapped[str | None] = mapped_column(String(120))  # when not in the vendor list
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vendor: Mapped[Vendor | None] = relationship()


class MaintenanceReminder(IdMixin, TimestampMixin, Base):
    __tablename__ = "maintenance_reminders"
    __table_args__ = (
        CheckConstraint(f"kind IN {REMINDER_KINDS}", name="kind"),
        CheckConstraint(f"status IN {REMINDER_STATUSES}", name="status"),
        CheckConstraint("due_date IS NOT NULL OR due_mileage IS NOT NULL", name="has_due"),
        Index("ix_reminders_open_due", "status", "due_date"),
    )

    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_mileage: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL")
    )
    # Email reminders: one automatic email per reminder; "Send reminder" can resend by hand.
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str | None] = mapped_column(String(10))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
