import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, field_validator, model_validator

from app.schemas.common import ORMModel, ShortText, _strip

ContactMethod = Literal["phone", "text", "email"]
AppointmentStatus = Literal[
    "requested", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show"
]

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_OLD_VIN_RE = re.compile(r"^[A-Z0-9]{5,16}$")  # pre-1981 VINs vary in length


def normalize_vin(v):
    v = _strip(v)
    if v is None:
        return None
    v = re.sub(r"[\s-]", "", str(v)).upper()
    if len(v) == 17:
        if not _VIN_RE.match(v):
            raise ValueError("A 17-character VIN can't contain the letters I, O, or Q.")
    elif not _OLD_VIN_RE.match(v):
        raise ValueError("VIN should be 17 letters and numbers (older vehicles may be shorter).")
    return v


def normalize_plate(v):
    v = _strip(v)
    return re.sub(r"\s+", "", v).upper() if v else None


Vin = Annotated[str | None, BeforeValidator(normalize_vin)]
Plate = Annotated[
    Annotated[str, Field(max_length=15)] | None,
    BeforeValidator(normalize_plate),
    Field(default=None),
]
Email = Annotated[EmailStr | None, BeforeValidator(_strip)]
Year = Annotated[int | None, Field(default=None, ge=1900, le=2100)]
Mileage = Annotated[int | None, Field(default=None, ge=0, le=5_000_000)]


# ---------- vehicles ----------


class VehicleFields(BaseModel):
    year: Year = None
    make: ShortText(60) = None
    model: ShortText(80) = None
    trim: ShortText(80) = None
    vin: Vin = None
    license_plate: Plate = None
    license_state: ShortText(10) = None
    mileage: Mileage = None
    engine: ShortText(80) = None
    transmission: ShortText(80) = None
    color: ShortText(40) = None
    internal_notes: ShortText(5000) = None


class VehicleCreate(VehicleFields):
    customer_id: int

    @model_validator(mode="after")
    def needs_identity(self):
        if not (self.make or self.model or self.vin or self.license_plate):
            raise ValueError("Enter at least a make, model, VIN, or license plate.")
        return self


class VehicleInline(VehicleFields):
    """Vehicle added in the same step as a new customer."""

    @model_validator(mode="after")
    def needs_identity(self):
        if not (self.make or self.model or self.vin or self.license_plate):
            raise ValueError("Enter at least a make, model, VIN, or license plate.")
        return self


class VehicleUpdate(VehicleFields):
    customer_id: int | None = None  # allows transferring a vehicle to a new owner


class VehicleOut(ORMModel):
    id: int
    customer_id: int
    year: int | None
    make: str | None
    model: str | None
    trim: str | None
    vin: str | None
    license_plate: str | None
    license_state: str | None
    mileage: int | None
    engine: str | None
    transmission: str | None
    color: str | None
    internal_notes: str | None
    display_name: str
    archived_at: datetime | None
    created_at: datetime


# ---------- customers ----------


class CustomerFields(BaseModel):
    first_name: ShortText(80) = None
    last_name: ShortText(80) = None
    phone: ShortText(40) = None
    email: Email = None
    address_line1: ShortText(200) = None
    address_line2: ShortText(200) = None
    city: ShortText(100) = None
    state: ShortText(50) = None
    postal_code: ShortText(20) = None
    preferred_contact: ContactMethod | None = None
    internal_notes: ShortText(5000) = None


class CustomerCreate(CustomerFields):
    first_name: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=80)]
    vehicle: VehicleInline | None = None

    @model_validator(mode="after")
    def needs_contact(self):
        if not (self.phone or self.email):
            raise ValueError("Enter a phone number or email so you can reach the customer.")
        return self


class CustomerUpdate(CustomerFields):
    @field_validator("first_name")
    @classmethod
    def first_name_not_blank(cls, v):
        # Explicit null/blank would erase the name; only allow it to be changed, not cleared.
        if v is None:
            raise ValueError("First name can't be blank.")
        return v


class CustomerOut(ORMModel):
    id: int
    first_name: str
    last_name: str
    full_name: str
    phone: str | None
    email: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    preferred_contact: str | None
    internal_notes: str | None
    customer_since: date
    archived_at: datetime | None
    created_at: datetime


class CustomerListItem(ORMModel):
    id: int
    full_name: str
    phone: str | None
    email: str | None
    vehicle_count: int = 0
    balance_cents: int = 0
    archived_at: datetime | None


class CustomerDetail(CustomerOut):
    vehicles: list[VehicleOut]
    balance_cents: int
    lifetime_paid_cents: int


# ---------- appointments ----------


class AppointmentFields(BaseModel):
    customer_id: int | None = None
    vehicle_id: int | None = None
    work_order_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    requested_service: ShortText(200) = None
    concern: ShortText(5000) = None
    customer_notes: ShortText(5000) = None
    internal_notes: ShortText(5000) = None

    @model_validator(mode="after")
    def time_order(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("End time must be after start time.")
        for name in ("starts_at", "ends_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must include a time zone offset.")
        return self


class AppointmentCreate(AppointmentFields):
    customer_id: int
    status: AppointmentStatus = "confirmed"


class AppointmentUpdate(AppointmentFields):
    status: AppointmentStatus | None = None


class AppointmentOut(ORMModel):
    id: int
    status: str
    customer_id: int | None
    vehicle_id: int | None
    work_order_id: int | None
    starts_at: datetime | None
    ends_at: datetime | None
    requested_service: str | None
    concern: str | None
    customer_notes: str | None
    internal_notes: str | None
    source: str
    preferred_date: date | None
    preferred_time: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    vehicle_description: str | None
    reported_mileage: int | None
    customer_name: str | None = None
    vehicle_name: str | None = None
    created_at: datetime
