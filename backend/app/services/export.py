"""CSV export of the shop's data (spec §36), so it never depends on this app to get it out.

Cells that a spreadsheet would treat as a formula (starting with = + - @ or a tab) are
prefixed with an apostrophe, so a customer named "=HYPERLINK(...)" can't run anything when the
file is opened in Excel or Google Sheets.
"""

import csv
import io
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Customer,
    Expense,
    Invoice,
    Part,
    Payment,
    ServiceRecord,
    Vehicle,
    WorkOrder,
)


def _money(cents: int | None) -> str:
    return "" if cents is None else f"{Decimal(cents) / 100:.2f}"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if text and text[0] in "=+-@\t\r":
        text = "'" + text
    return text


Column = tuple[str, Callable]


def _customers(db: Session) -> tuple[list[Column], Iterable]:
    cols = [
        ("id", lambda c: c.id),
        ("first_name", lambda c: c.first_name),
        ("last_name", lambda c: c.last_name),
        ("phone", lambda c: c.phone),
        ("email", lambda c: c.email),
        ("address_line1", lambda c: c.address_line1),
        ("address_line2", lambda c: c.address_line2),
        ("city", lambda c: c.city),
        ("state", lambda c: c.state),
        ("postal_code", lambda c: c.postal_code),
        ("preferred_contact", lambda c: c.preferred_contact),
        ("internal_notes", lambda c: c.internal_notes),
        ("customer_since", lambda c: c.created_at.date()),
        ("archived", lambda c: c.archived_at is not None),
    ]
    return cols, db.scalars(select(Customer).order_by(Customer.id))


def _vehicles(db: Session):
    cols = [
        ("id", lambda v: v.id),
        ("customer_id", lambda v: v.customer_id),
        ("year", lambda v: v.year),
        ("make", lambda v: v.make),
        ("model", lambda v: v.model),
        ("trim", lambda v: v.trim),
        ("vin", lambda v: v.vin),
        ("license_plate", lambda v: v.license_plate),
        ("license_state", lambda v: v.license_state),
        ("mileage", lambda v: v.mileage),
        ("engine", lambda v: v.engine),
        ("transmission", lambda v: v.transmission),
        ("color", lambda v: v.color),
        ("internal_notes", lambda v: v.internal_notes),
        ("archived", lambda v: v.archived_at is not None),
    ]
    return cols, db.scalars(select(Vehicle).order_by(Vehicle.id))


def _work_orders(db: Session):
    cols = [
        ("number", lambda w: w.number),
        ("status", lambda w: w.status),
        ("opened", lambda w: w.created_at),
        ("completed", lambda w: w.completed_at),
        ("customer", lambda w: w.customer.full_name),
        ("vehicle", lambda w: w.vehicle.display_name),
        ("vin", lambda w: w.vehicle.vin),
        ("mileage_in", lambda w: w.mileage_in),
        ("mileage_out", lambda w: w.mileage_out),
        ("concern", lambda w: w.concern),
        ("labor", lambda w: _money(w.labor_cents)),
        ("parts", lambda w: _money(w.parts_cents)),
        ("fees", lambda w: _money(w.fees_cents)),
        ("discounts", lambda w: _money(w.discount_cents)),
        ("tax", lambda w: _money(w.tax_cents)),
        ("total", lambda w: _money(w.total_cents)),
        ("internal_notes", lambda w: w.internal_notes),
    ]
    q = select(WorkOrder).options(joinedload(WorkOrder.customer), joinedload(WorkOrder.vehicle))
    return cols, db.scalars(q.order_by(WorkOrder.id))


def _invoices(db: Session):
    cols = [
        ("number", lambda i: i.number),
        ("status", lambda i: i.status),
        ("issue_date", lambda i: i.issue_date),
        ("due_date", lambda i: i.due_date),
        ("customer", lambda i: i.customer.full_name),
        ("vehicle", lambda i: i.vehicle.display_name),
        ("labor", lambda i: _money(i.labor_cents)),
        ("parts", lambda i: _money(i.parts_cents)),
        ("fees", lambda i: _money(i.fees_cents)),
        ("discounts", lambda i: _money(i.discount_cents)),
        ("tax", lambda i: _money(i.tax_cents)),
        ("total", lambda i: _money(i.total_cents)),
        ("paid", lambda i: _money(i.amount_paid_cents)),
        ("balance", lambda i: _money(i.balance_cents)),
        ("void_reason", lambda i: i.void_reason),
    ]
    q = select(Invoice).options(joinedload(Invoice.customer), joinedload(Invoice.vehicle))
    return cols, db.scalars(q.order_by(Invoice.id))


def _payments(db: Session):
    cols = [
        ("id", lambda p: p.id),
        ("invoice", lambda p: p.invoice.number),
        ("paid_at", lambda p: p.paid_at),
        ("method", lambda p: p.method),
        ("status", lambda p: p.status),
        ("amount", lambda p: _money(p.amount_cents)),
        ("refunded", lambda p: _money(p.refunded_cents)),
        ("reference", lambda p: p.reference),
        ("stripe_payment", lambda p: p.provider_ref),
        ("notes", lambda p: p.notes),
    ]
    q = select(Payment).options(joinedload(Payment.invoice))
    return cols, db.scalars(q.order_by(Payment.id))


def _expenses(db: Session):
    cols = [
        ("date", lambda e: e.expense_date),
        ("vendor", lambda e: e.vendor.name if e.vendor else e.vendor_name),
        ("category", lambda e: e.category),
        ("amount", lambda e: _money(e.amount_cents)),
        ("description", lambda e: e.description),
    ]
    q = select(Expense).options(joinedload(Expense.vendor)).where(Expense.deleted_at.is_(None))
    return cols, db.scalars(q.order_by(Expense.expense_date, Expense.id))


def _parts(db: Session):
    cols = [
        ("name", lambda p: p.name),
        ("part_number", lambda p: p.part_number),
        ("category", lambda p: p.category),
        ("vendor", lambda p: p.vendor.name if p.vendor else None),
        ("cost", lambda p: _money(p.cost_cents)),
        ("price", lambda p: _money(p.price_cents)),
        ("quantity", lambda p: p.quantity),
        ("reorder_at", lambda p: p.reorder_at),
        ("warranty_months", lambda p: p.warranty_months),
        ("warranty_miles", lambda p: p.warranty_miles),
        ("archived", lambda p: p.archived_at is not None),
    ]
    return cols, db.scalars(select(Part).options(joinedload(Part.vendor)).order_by(Part.name))


def _service_history(db: Session):
    cols = [
        ("vehicle_id", lambda r: r.vehicle_id),
        ("date", lambda r: r.service_date),
        ("mileage", lambda r: r.mileage),
        ("summary", lambda r: r.summary),
        ("source", lambda r: r.source),
        ("performed_by", lambda r: r.performed_by),
        ("total", lambda r: _money(r.total_cents)),
        ("notes", lambda r: r.notes),
    ]
    q = select(ServiceRecord).where(ServiceRecord.deleted_at.is_(None))
    return cols, db.scalars(q.order_by(ServiceRecord.vehicle_id, ServiceRecord.service_date))


DATASETS = {
    "customers": _customers,
    "vehicles": _vehicles,
    "work_orders": _work_orders,
    "invoices": _invoices,
    "payments": _payments,
    "expenses": _expenses,
    "parts": _parts,
    "service_history": _service_history,
}


def to_csv(db: Session, dataset: str) -> tuple[str, int]:
    cols, rows = DATASETS[dataset](db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([name for name, _ in cols])
    n = 0
    for row in rows.unique() if hasattr(rows, "unique") else rows:
        w.writerow([_cell(get(row)) for _, get in cols])
        n += 1
    # A byte-order mark so Excel opens accented names correctly.
    return "﻿" + buf.getvalue(), n
