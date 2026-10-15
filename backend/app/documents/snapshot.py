"""Customer-safe snapshots of documents.

A snapshot is everything a customer may see on a document, and nothing else: no part costs,
markups, internal notes, or vendor account details. The same structure feeds the PDF, the
customer's link page, and the content hash recorded when a document is signed.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Business, Customer, Estimate, Invoice, Payment, Vehicle, WorkOrder
from app.services.business import get_business, shop_today

KIND_LABEL = {"labor": "Labor", "part": "Part", "fee": "Fee", "discount": "Discount"}


def _iso(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v.normalize()) if v == v.to_integral() else str(v)
    return v


def content_hash(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=_iso)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _address(*parts: str | None) -> list[str]:
    return [p for p in parts if p]


def _business(b: Business) -> dict:
    city_line = " ".join(
        p for p in [", ".join(p for p in [b.city, b.state] if p), b.postal_code] if p
    )
    return {
        "name": b.name,
        "phone": b.phone,
        "email": b.email,
        "website": b.website,
        "address": _address(b.address_line1, b.address_line2, city_line or None),
        "logo_key": b.logo_key,
    }


def _customer(c: Customer) -> dict:
    city_line = " ".join(
        p for p in [", ".join(p for p in [c.city, c.state] if p), c.postal_code] if p
    )
    return {
        "name": c.full_name,
        "phone": c.phone,
        "email": c.email,
        "address": _address(c.address_line1, c.address_line2, city_line or None),
    }


def _vehicle(v: Vehicle, mileage: int | None) -> dict:
    return {
        "description": v.display_name,
        "vin": v.vin,
        "plate": " ".join(p for p in [v.license_plate, v.license_state] if p) or None,
        "mileage": mileage if mileage is not None else v.mileage,
    }


def _items(items) -> list[dict]:
    out = []
    for li in items:
        warranty = ", ".join(
            p
            for p in [
                f"{li.warranty_months} mo" if li.warranty_months else None,
                f"{li.warranty_miles:,} mi" if li.warranty_miles else None,
                li.warranty_notes,
            ]
            if p
        )
        out.append(
            {
                "kind": li.kind,
                "kind_label": KIND_LABEL[li.kind],
                "description": li.description,
                "quantity": _iso(Decimal(li.quantity)),
                "unit_price_cents": li.unit_price_cents,
                "line_total_cents": li.line_total_cents,
                "taxable": li.taxable,
                "part_number": li.part_number,
                "warranty": warranty or None,
            }
        )
    return out


def _totals(doc) -> dict:
    return {
        "tax_rate": _iso(Decimal(doc.tax_rate)),
        "labor_cents": doc.labor_cents,
        "parts_cents": doc.parts_cents,
        "fees_cents": doc.fees_cents,
        "discount_cents": doc.discount_cents,
        "taxable_cents": doc.taxable_cents,
        "tax_cents": doc.tax_cents,
        "total_cents": doc.total_cents,
    }


def snapshot_estimate(db: Session, est: Estimate) -> dict:
    b = get_business(db)
    return {
        "doc_type": "estimate",
        "title": "Additional work approval" if est.is_supplement else "Repair estimate",
        "number": est.number,
        "version": est.version,
        "date": _iso(shop_today(b)),
        "expires_on": _iso(est.expires_on),
        "business": _business(b),
        "customer": _customer(est.customer),
        "vehicle": _vehicle(est.vehicle, est.mileage),
        "concern": est.concern,
        "notes": est.customer_notes,
        "items": _items(est.items),
        "totals": _totals(est),
        "authorization_statement": b.authorization_statement,
        "terms": b.terms_text,
        "footer": None,
    }


def snapshot_work_order(db: Session, wo: WorkOrder, version: int) -> dict:
    b = get_business(db)
    return {
        "doc_type": "work_order",
        "title": "Repair authorization",
        "number": wo.number,
        "version": version,
        "date": _iso(shop_today(b)),
        "business": _business(b),
        "customer": _customer(wo.customer),
        "vehicle": _vehicle(wo.vehicle, wo.mileage_in),
        "concern": wo.concern,
        "notes": wo.customer_notes,
        "items": _items(wo.items),
        "totals": _totals(wo),
        "authorization_statement": b.authorization_statement,
        "terms": b.terms_text,
        "footer": None,
    }


def snapshot_invoice(db: Session, inv: Invoice, version: int | None = None) -> dict:
    b = get_business(db)
    payments = [
        {
            "date": _iso(p.paid_at.date()),
            "method": p.method,
            "amount_cents": p.amount_cents,
            "reference": p.reference if p.method == "check" else None,
        }
        for p in inv.payments
        if p.status == "succeeded"
    ]
    return {
        "doc_type": "invoice",
        "title": "Invoice",
        "number": inv.number,
        "version": version,
        "status": inv.status,
        "date": _iso(inv.issue_date),
        "due_date": _iso(inv.due_date),
        "business": _business(b),
        "customer": _customer(inv.customer),
        "vehicle": _vehicle(inv.vehicle, inv.mileage),
        "concern": None,
        "notes": inv.customer_notes,
        "items": _items(inv.items),
        "totals": _totals(inv),
        "amount_paid_cents": inv.amount_paid_cents,
        "balance_cents": inv.balance_cents,
        "payments": payments,
        "footer": b.invoice_footer,
    }


def snapshot_receipt(db: Session, payment: Payment) -> dict:
    b = get_business(db)
    inv = payment.invoice
    return {
        "doc_type": "receipt",
        "title": "Payment receipt",
        "number": f"{inv.number}-R{payment.id}",
        "invoice_number": inv.number,
        "date": _iso(payment.paid_at.date()),
        "business": _business(b),
        "customer": _customer(inv.customer),
        "vehicle": _vehicle(inv.vehicle, inv.mileage),
        "payment": {
            "amount_cents": payment.amount_cents,
            "method": payment.method,
            "reference": payment.reference if payment.method == "check" else None,
            "paid_at": _iso(payment.paid_at),
            "status": payment.status,
        },
        "invoice_total_cents": inv.total_cents,
        # Balance right after this payment, so a receipt printed later still tells the truth.
        "balance_cents": max(
            inv.total_cents
            - sum(
                p.amount_cents
                for p in inv.payments
                if p.status == "succeeded" and (p.paid_at, p.id) <= (payment.paid_at, payment.id)
            ),
            0,
        ),
        "footer": b.invoice_footer or "Thank you for your business.",
    }
