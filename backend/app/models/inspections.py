"""Digital inspections, photos, and the vehicle service history.

- An inspection belongs to one work order. Each item gets a status (good / monitor / needs
  attention / urgent), optional customer-facing notes, a recommended repair with an
  estimated cost, and photos.
- Photos are re-encoded on upload (location and camera data removed) and stored privately.
  They're attached to one thing (an inspection item, work order, estimate, vehicle, or
  customer); deleting one only hides it, so anything a customer signed keeps its pictures.
- A service record is written automatically when a work order is completed, and can be
  added by hand for work done before the shop used this app. It is the vehicle's long-term
  maintenance record.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin
from app.models.customers import Customer, Vehicle

INSPECTION_STATUSES = ("in_progress", "completed")
ITEM_STATUSES = ("good", "monitor", "attention", "urgent")
PHOTO_ENTITIES = ("inspection_item", "work_order", "estimate", "vehicle", "customer", "expense")
SERVICE_SOURCES = ("work_order", "manual")

# The categories spec §6 lists, in the order a mechanic walks around a car.
DEFAULT_ITEMS = (
    ("Engine", "Engine (leaks, noises, mounts)"),
    ("Transmission", "Transmission"),
    ("Brakes", "Brakes (pads, rotors, lines)"),
    ("Tires", "Tires (tread, wear, pressure)"),
    ("Suspension", "Suspension"),
    ("Steering", "Steering"),
    ("Battery", "Battery and charging"),
    ("Fluids", "Fluids (oil, coolant, brake, transmission)"),
    ("Lights", "Lights"),
    ("Belts", "Belts"),
    ("Hoses", "Hoses"),
    ("Cooling", "Cooling system"),
    ("AC", "Air conditioning and heat"),
    ("Electrical", "Electrical"),
)


class Inspection(IdMixin, TimestampMixin, Base):
    __tablename__ = "inspections"
    __table_args__ = (CheckConstraint(f"status IN {INSPECTION_STATUSES}", name="status"),)

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="in_progress")
    mileage: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)  # shown to the customer
    internal_notes: Mapped[str | None] = mapped_column(Text)  # never shown to customers
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship()
    vehicle: Mapped[Vehicle] = relationship()
    items: Mapped[list["InspectionItem"]] = relationship(
        back_populates="inspection",
        order_by="InspectionItem.position, InspectionItem.id",
        cascade="all, delete-orphan",
    )


class InspectionItem(IdMixin, Base):
    __tablename__ = "inspection_items"
    __table_args__ = (
        CheckConstraint(f"status IS NULL OR status IN {ITEM_STATUSES}", name="status"),
        CheckConstraint(
            "estimated_cost_cents IS NULL OR estimated_cost_cents >= 0", name="cost_nonnegative"
        ),
    )

    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str | None] = mapped_column(String(10))  # NULL = not checked yet
    notes: Mapped[str | None] = mapped_column(Text)  # shown to the customer
    recommendation: Mapped[str | None] = mapped_column(String(300))
    estimated_cost_cents: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    inspection: Mapped[Inspection] = relationship(back_populates="items")


class Photo(IdMixin, Base):
    __tablename__ = "photos"
    __table_args__ = (
        CheckConstraint(f"entity_type IN {PHOTO_ENTITIES}", name="entity_type"),
        Index("ix_photos_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Denormalized so a vehicle's or customer's photos can be listed in one query.
    # Empty for shop photos such as expense receipts.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    thumb_key: Mapped[str] = mapped_column(String(300), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(300))
    # Included on documents the customer sees (inspection report, estimate, work order).
    customer_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServiceRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "service_records"
    __table_args__ = (
        CheckConstraint(f"source IN {SERVICE_SOURCES}", name="source"),
        Index("ix_service_records_vehicle_date", "vehicle_id", "service_date"),
    )

    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), unique=True
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    mileage: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    # Lines as performed: [{kind, description, quantity, part_number, warranty_months,
    # warranty_miles, warranty_notes}]. Prices are deliberately not repeated here.
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    labor_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parts_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cents: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[str | None] = mapped_column(String(120))  # for manual records
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
