from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.schemas.common import ORMModel, ShortText, _strip

LineKind = Literal["labor", "part", "fee", "discount"]
WorkOrderStatus = Literal[
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
]
PaymentMethod = Literal["cash", "check", "card", "online", "other"]
Cents = Annotated[int, Field(ge=0, le=100_000_000)]  # up to $1,000,000.00


class LineItemIn(BaseModel):
    kind: LineKind
    description: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=300)]
    quantity: Annotated[Decimal, Field(gt=0, le=10_000, max_digits=10, decimal_places=2)] = Decimal(
        "1"
    )
    # Omit for labor to use the shop's default rate, or for parts to derive from cost + markup.
    unit_price_cents: Cents | None = None
    unit_cost_cents: Cents | None = None
    markup_pct: Annotated[Decimal, Field(ge=0, le=1000, decimal_places=2)] | None = None
    # Omit to use the shop's default taxability for this kind of line.
    taxable: bool | None = None
    part_number: ShortText(80) = None
    vendor_name: ShortText(120) = None
    warranty_months: Annotated[int, Field(ge=0, le=600)] | None = None
    warranty_miles: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    warranty_notes: ShortText(300) = None
    # From the parts list (stock comes out when the work order is completed).
    part_id: int | None = None

    @model_validator(mode="after")
    def price_is_determinable(self):
        if self.unit_price_cents is None and self.kind in ("fee", "discount"):
            raise ValueError("Enter an amount for fees and discounts.")
        if self.unit_price_cents is None and self.kind == "part" and self.unit_cost_cents is None:
            raise ValueError("Enter a price for the part, or its cost so markup can be applied.")
        if self.kind != "part" and (
            self.unit_cost_cents is not None or self.markup_pct is not None
        ):
            raise ValueError("Cost and markup only apply to parts.")
        return self


class LineItemOut(ORMModel):
    id: int
    position: int
    kind: str
    description: str
    quantity: Decimal
    unit_price_cents: int
    unit_cost_cents: int | None
    markup_pct: Decimal | None
    taxable: bool
    line_total_cents: int
    part_number: str | None
    vendor_name: str | None
    warranty_months: int | None
    warranty_miles: int | None
    warranty_notes: str | None
    part_id: int | None = None


class TotalsOut(ORMModel):
    tax_rate: Decimal
    labor_cents: int
    parts_cents: int
    fees_cents: int
    discount_cents: int
    taxable_cents: int
    tax_cents: int
    total_cents: int


class PartyOut(BaseModel):
    """Customer and vehicle summary embedded in documents."""

    customer_id: int
    customer_name: str
    customer_phone: str | None
    customer_email: str | None
    vehicle_id: int
    vehicle_name: str
    vin: str | None
    license_plate: str | None


# ---------- work orders ----------


class WorkOrderCreate(BaseModel):
    customer_id: int
    vehicle_id: int
    concern: ShortText(5000) = None
    customer_notes: ShortText(5000) = None
    internal_notes: ShortText(5000) = None
    mileage_in: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    promised_at: datetime | None = None
    appointment_id: int | None = None
    items: list[LineItemIn] = Field(default_factory=list, max_length=200)


class WorkOrderUpdate(BaseModel):
    concern: ShortText(5000) = None
    customer_notes: ShortText(5000) = None
    # Longer than other notes: the running repair log below appends to it.
    internal_notes: ShortText(20000) = None
    mileage_in: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    mileage_out: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    promised_at: datetime | None = None
    qc_checklist: dict[str, bool] | None = None


class WorkOrderNoteIn(BaseModel):
    text: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=2000)]


class StatusChange(BaseModel):
    status: WorkOrderStatus
    # Completing without every QC item checked requires an explicit override.
    override_checklist: bool = False
    # With status ready_for_pickup: email the customer that the vehicle is ready.
    notify_customer: bool = False


class WorkOrderOut(TotalsOut):
    id: int
    number: str
    status: str
    customer_id: int
    vehicle_id: int
    concern: str | None
    customer_notes: str | None
    internal_notes: str | None
    mileage_in: int | None
    mileage_out: int | None
    promised_at: datetime | None
    qc_checklist: dict
    completed_at: datetime | None
    inspection_id: int | None = None
    created_at: datetime
    updated_at: datetime
    party: PartyOut | None = None
    items: list[LineItemOut] = []
    invoice_ids: list[int] = []
    estimate_ids: list[int] = []
    authorization: dict | None = None
    email: dict | None = None


class WorkOrderCard(BaseModel):
    """Compact work order for lists and the status board."""

    id: int
    number: str
    status: str
    customer_name: str
    vehicle_name: str
    concern: str | None
    total_cents: int
    promised_at: datetime | None
    updated_at: datetime


# ---------- estimates ----------


class EstimateCreate(BaseModel):
    customer_id: int
    vehicle_id: int
    work_order_id: int | None = None
    concern: ShortText(5000) = None
    customer_notes: ShortText(5000) = None
    internal_notes: ShortText(5000) = None
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    expires_on: date | None = None
    # When created from a work order with no items given, its current lines are copied.
    items: list[LineItemIn] | None = Field(default=None, max_length=200)
    # Approval request for additional work on an open work order; lines are added on approval.
    is_supplement: bool = False


class EstimateUpdate(BaseModel):
    concern: ShortText(5000) = None
    # Show this inspection's findings and photos with the estimate (null to detach).
    inspection_id: int | None = None
    customer_notes: ShortText(5000) = None
    internal_notes: ShortText(5000) = None
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    expires_on: date | None = None


class DecisionIn(BaseModel):
    decision: Literal["approved", "declined"]
    method: Literal["in_person", "phone", "email", "text"]
    note: ShortText(500) = None


class EstimateOut(TotalsOut):
    id: int
    number: str
    version: int
    status: str
    customer_id: int
    vehicle_id: int
    work_order_id: int | None
    inspection_id: int | None = None
    concern: str | None
    customer_notes: str | None
    internal_notes: str | None
    mileage: int | None
    expires_on: date | None
    sent_at: datetime | None
    viewed_at: datetime | None
    approved_at: datetime | None
    declined_at: datetime | None
    locked_at: datetime | None
    decision_method: str | None
    decision_note: str | None
    converted_at: datetime | None
    is_supplement: bool
    created_at: datetime
    updated_at: datetime
    party: PartyOut | None = None
    items: list[LineItemOut] = []
    authorization: dict | None = None


# ---------- invoices & payments ----------


class InvoiceCreate(BaseModel):
    customer_id: int
    vehicle_id: int
    issue_date: date | None = None
    due_date: date | None = None
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    customer_notes: ShortText(5000) = None
    internal_notes: ShortText(5000) = None
    items: list[LineItemIn] = Field(default_factory=list, max_length=200)


class InvoiceFromWorkOrder(BaseModel):
    due_date: date | None = None
    customer_notes: ShortText(5000) = None


class InvoiceUpdate(BaseModel):
    issue_date: date | None = None
    due_date: date | None = None
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    customer_notes: ShortText(5000) = None
    internal_notes: ShortText(5000) = None


class VoidIn(BaseModel):
    reason: Annotated[str, BeforeValidator(_strip), Field(min_length=3, max_length=300)]


class PaymentIn(BaseModel):
    amount_cents: Annotated[int, Field(gt=0, le=100_000_000)]
    method: PaymentMethod
    paid_at: datetime | None = None
    reference: ShortText(120) = None
    notes: ShortText(500) = None


class PaymentOut(ORMModel):
    id: int
    invoice_id: int
    amount_cents: int
    method: str
    status: str
    paid_at: datetime
    reference: str | None
    provider_ref: str | None
    notes: str | None
    voided_at: datetime | None
    void_reason: str | None
    refunded_cents: int
    refunded_at: datetime | None
    created_at: datetime
    invoice_number: str | None = None


class InvoiceOut(TotalsOut):
    id: int
    number: str
    status: str
    customer_id: int
    vehicle_id: int
    work_order_id: int | None
    issue_date: date
    due_date: date | None
    mileage: int | None
    customer_notes: str | None
    internal_notes: str | None
    amount_paid_cents: int
    balance_cents: int
    overpaid_cents: int
    sent_at: datetime | None
    viewed_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime
    updated_at: datetime
    party: PartyOut | None = None
    items: list[LineItemOut] = []
    payments: list[PaymentOut] = []


class DocumentListItem(BaseModel):
    id: int
    number: str
    status: str
    customer_name: str
    vehicle_name: str
    total_cents: int
    balance_cents: int | None = None
    date: date
