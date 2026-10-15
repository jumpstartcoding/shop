"""Build response models that need data from more than one row."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Estimate, Invoice, WorkOrder
from app.schemas.documents import (
    EstimateOut,
    InvoiceOut,
    LineItemOut,
    PartyOut,
    PaymentOut,
    WorkOrderCard,
    WorkOrderOut,
)


def party(doc) -> PartyOut:
    c, v = doc.customer, doc.vehicle
    return PartyOut(
        customer_id=c.id,
        customer_name=c.full_name,
        customer_phone=c.phone,
        customer_email=c.email,
        vehicle_id=v.id,
        vehicle_name=v.display_name,
        vin=v.vin,
        license_plate=v.license_plate,
    )


def _items(doc) -> list[LineItemOut]:
    return [LineItemOut.model_validate(li) for li in doc.items]


def work_order_out(db: Session, wo: WorkOrder) -> WorkOrderOut:
    out = WorkOrderOut.model_validate(wo, from_attributes=True)
    out.party = party(wo)
    out.items = _items(wo)
    out.invoice_ids = list(
        db.scalars(select(Invoice.id).where(Invoice.work_order_id == wo.id).order_by(Invoice.id))
    )
    out.estimate_ids = list(
        db.scalars(select(Estimate.id).where(Estimate.work_order_id == wo.id).order_by(Estimate.id))
    )
    return out


def work_order_card(wo: WorkOrder) -> WorkOrderCard:
    return WorkOrderCard(
        id=wo.id,
        number=wo.number,
        status=wo.status,
        customer_name=wo.customer.full_name,
        vehicle_name=wo.vehicle.display_name,
        concern=wo.concern,
        total_cents=wo.total_cents,
        promised_at=wo.promised_at,
        updated_at=wo.updated_at,
    )


def estimate_out(est: Estimate) -> EstimateOut:
    out = EstimateOut.model_validate(est, from_attributes=True)
    out.party = party(est)
    out.items = _items(est)
    return out


def invoice_out(inv: Invoice) -> InvoiceOut:
    out = InvoiceOut.model_validate(inv, from_attributes=True)
    out.party = party(inv)
    out.items = _items(inv)
    out.payments = [PaymentOut.model_validate(p) for p in inv.payments]
    return out
