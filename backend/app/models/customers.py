"""Customers, vehicles, appointments."""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ArchiveMixin, Base, IdMixin, TimestampMixin

CONTACT_METHODS = ("phone", "text", "email")
APPOINTMENT_STATUSES = (
    "requested",
    "confirmed",
    "checked_in",
    "in_progress",
    "completed",
    "cancelled",
    "no_show",
)


class Customer(IdMixin, TimestampMixin, ArchiveMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            f"preferred_contact IS NULL OR preferred_contact IN {CONTACT_METHODS}",
            name="preferred_contact",
        ),
        Index(
            "ix_customers_name_trgm",
            text("(lower(first_name || ' ' || last_name)) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index("ix_customers_phone_digits", "phone_digits"),
        Index("ix_customers_email_lower", func.lower(text("email"))),
    )

    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    phone: Mapped[str | None] = mapped_column(String(40))
    # Digits only, maintained by the app, so "(555) 123-4567" matches "5551234567".
    phone_digits: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    preferred_contact: Mapped[str | None] = mapped_column(String(10))
    # Never serialized to customer-facing responses.
    internal_notes: Mapped[str | None] = mapped_column(Text)
    customer_since: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )

    vehicles: Mapped[list["Vehicle"]] = relationship(
        back_populates="customer", order_by="Vehicle.id"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Vehicle(IdMixin, TimestampMixin, ArchiveMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("year IS NULL OR (year >= 1900 AND year <= 2100)", name="year"),
        CheckConstraint("mileage IS NULL OR mileage >= 0", name="mileage"),
        Index("uq_vehicles_vin", "vin", unique=True, postgresql_where=text("vin IS NOT NULL")),
        Index("ix_vehicles_plate", func.upper(text("license_plate"))),
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    trim: Mapped[str | None] = mapped_column(String(80))
    vin: Mapped[str | None] = mapped_column(String(17))
    license_plate: Mapped[str | None] = mapped_column(String(15))
    license_state: Mapped[str | None] = mapped_column(String(10))
    mileage: Mapped[int | None] = mapped_column(Integer)
    engine: Mapped[str | None] = mapped_column(String(80))
    transmission: Mapped[str | None] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(40))
    internal_notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(back_populates="vehicles")

    @property
    def display_name(self) -> str:
        parts = [str(self.year) if self.year else None, self.make, self.model, self.trim]
        return " ".join(p for p in parts if p) or "Vehicle"


class Appointment(IdMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(f"status IN {APPOINTMENT_STATUSES}", name="status"),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="time_order"
        ),
    )

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    # Confirmed slot. NULL while only a preferred date/time has been requested.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_service: Mapped[str | None] = mapped_column(String(200))
    concern: Mapped[str | None] = mapped_column(Text)
    customer_notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="admin"
    )  # admin | online

    # Snapshot of what was submitted through the public booking form, before matching
    # to a customer record. Kept so nothing the customer typed is lost.
    preferred_date: Mapped[date | None] = mapped_column(Date)
    preferred_time: Mapped[str | None] = mapped_column(String(40))
    contact_name: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    vehicle_description: Mapped[str | None] = mapped_column(String(200))
    reported_mileage: Mapped[int | None] = mapped_column(Integer)

    customer: Mapped[Customer | None] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()
