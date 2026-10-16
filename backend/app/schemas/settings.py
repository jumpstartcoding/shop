import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, field_validator

from app.schemas.common import ORMModel, ShortText, _strip

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_PREFIX = re.compile(r"^[A-Z0-9]{1,10}$")


class DayHours(BaseModel):
    open: str
    close: str

    @field_validator("open", "close")
    @classmethod
    def hhmm(cls, v: str) -> str:
        if not _TIME.match(v):
            raise ValueError("Use 24-hour HH:MM, for example 08:00 or 17:30.")
        return v


def _prefix(v):
    v = _strip(v)
    if v is None:
        return v
    v = v.upper()
    if not _PREFIX.match(v):
        raise ValueError("Use 1-10 letters or numbers.")
    return v


Prefix = Annotated[str | None, BeforeValidator(_prefix)]


class Testimonial(BaseModel):
    name: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=80)]
    text: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=600)]


class BusinessUpdate(BaseModel):
    name: ShortText(160) = None
    phone: ShortText(40) = None
    email: Annotated[EmailStr | None, BeforeValidator(_strip)] = None
    website: ShortText(254) = None
    address_line1: ShortText(200) = None
    address_line2: ShortText(200) = None
    city: ShortText(100) = None
    state: ShortText(50) = None
    postal_code: ShortText(20) = None
    service_area: ShortText(2000) = None
    hours: dict[str, DayHours | None] | None = None
    about_text: ShortText(10000) = None
    certifications: ShortText(2000) = None
    offers_towing: bool | None = None
    towing_info: ShortText(2000) = None
    financing_info: ShortText(2000) = None
    social_links: dict[str, Annotated[str, Field(max_length=300)]] | None = None
    timezone: str | None = None
    tax_rate: Annotated[Decimal, Field(ge=0, le=30, decimal_places=4)] | None = None
    tax_labor: bool | None = None
    tax_parts: bool | None = None
    tax_fees: bool | None = None
    default_labor_rate_cents: Annotated[int, Field(ge=0, le=10_000_00)] | None = None
    default_parts_markup_pct: Annotated[Decimal, Field(ge=0, le=1000, decimal_places=2)] | None = (
        None
    )
    invoice_prefix: Prefix = None
    estimate_prefix: Prefix = None
    work_order_prefix: Prefix = None
    invoice_due_days: Annotated[int, Field(ge=0, le=120)] | None = None
    estimate_valid_days: Annotated[int, Field(ge=1, le=365)] | None = None
    authorization_statement: ShortText(2000) = None
    inspection_statement: ShortText(2000) = None
    allow_typed_signature: bool | None = None
    invoice_footer: ShortText(2000) = None
    terms_text: ShortText(5000) = None
    notify_by_email: bool | None = None
    reminder_emails: bool | None = None
    reminder_lead_days: Annotated[int, Field(ge=0, le=90)] | None = None
    testimonials: list[Testimonial] | None = Field(default=None, max_length=12)
    online_payments_enabled: bool | None = None
    reviews_url: ShortText(300) = None

    @field_validator("hours")
    @classmethod
    def known_days(cls, v):
        if v is not None and set(v) - set(DAYS):
            raise ValueError(f"Days must be among {', '.join(DAYS)}.")
        return v

    @field_validator("timezone")
    @classmethod
    def valid_tz(cls, v):
        if v is not None and v not in available_timezones():
            raise ValueError("Unknown time zone.")
        return v


class BusinessOut(ORMModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    website: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    service_area: str | None
    hours: dict
    about_text: str | None
    certifications: str | None
    offers_towing: bool
    towing_info: str | None
    financing_info: str | None
    social_links: dict
    timezone: str
    tax_rate: Decimal
    tax_labor: bool
    tax_parts: bool
    tax_fees: bool
    default_labor_rate_cents: int
    default_parts_markup_pct: Decimal
    invoice_prefix: str
    estimate_prefix: str
    work_order_prefix: str
    invoice_due_days: int
    estimate_valid_days: int
    authorization_statement: str
    inspection_statement: str
    allow_typed_signature: bool
    invoice_footer: str | None
    terms_text: str | None
    notify_by_email: bool
    reminder_emails: bool
    reminder_lead_days: int
    logo_key: str | None
    testimonials: list
    reviews_url: str | None
    online_payments_enabled: bool


class PublicBusinessOut(ORMModel):
    """What the public website may show. No pricing defaults or internal settings."""

    name: str
    phone: str | None
    email: str | None
    website: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    service_area: str | None
    hours: dict
    about_text: str | None
    certifications: str | None
    offers_towing: bool
    towing_info: str | None
    financing_info: str | None
    social_links: dict
    testimonials: list
    reviews_url: str | None
    timezone: str
    has_logo: bool = False


class ServiceIn(BaseModel):
    name: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=120)]
    category: ShortText(80) = None
    description: ShortText(5000) = None
    starting_price_cents: Annotated[int, Field(ge=0, le=100_000_00)] | None = None
    sort_order: int = 0
    is_published: bool = True


class ServiceUpdate(BaseModel):
    name: ShortText(120) = None
    category: ShortText(80) = None
    description: ShortText(5000) = None
    starting_price_cents: Annotated[int, Field(ge=0, le=100_000_00)] | None = None
    sort_order: int | None = None
    is_published: bool | None = None


class ServiceOut(ORMModel):
    id: int
    name: str
    slug: str
    category: str | None
    description: str | None
    starting_price_cents: int | None
    sort_order: int
    is_published: bool
    archived_at: datetime | None = None
