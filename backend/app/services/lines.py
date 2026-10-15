"""Building, copying, and pricing line items for any document type."""

from collections.abc import Sequence
from decimal import Decimal

from app.core.pricing import compute_totals, line_total_cents, price_from_markup
from app.models import Business
from app.models.documents import LineItemMixin, TotalsMixin
from app.schemas.documents import LineItemIn

_COPY_FIELDS = (
    "kind",
    "description",
    "quantity",
    "unit_price_cents",
    "unit_cost_cents",
    "markup_pct",
    "taxable",
    "part_number",
    "vendor_name",
    "warranty_months",
    "warranty_miles",
    "warranty_notes",
)


def default_taxable(business: Business, kind: str) -> bool:
    return {
        "labor": business.tax_labor,
        "part": business.tax_parts,
        "fee": business.tax_fees,
        # A discount reduces the taxable base when it applies to taxable work. Default it to
        # follow parts, the most commonly taxed line; the mechanic can override per line.
        "discount": business.tax_parts,
    }[kind]


def build_line(model: type[LineItemMixin], data: LineItemIn, business: Business, position: int):
    price = data.unit_price_cents
    markup = data.markup_pct
    if price is None and data.kind == "labor":
        price = business.default_labor_rate_cents
    if price is None and data.kind == "part":
        if markup is None:
            markup = business.default_parts_markup_pct
        price = price_from_markup(data.unit_cost_cents or 0, markup)
    assert price is not None  # guaranteed by LineItemIn validation

    taxable = data.taxable if data.taxable is not None else default_taxable(business, data.kind)
    return model(
        position=position,
        kind=data.kind,
        description=data.description,
        quantity=data.quantity,
        unit_price_cents=price,
        unit_cost_cents=data.unit_cost_cents,
        markup_pct=markup if data.kind == "part" else None,
        taxable=taxable,
        line_total_cents=line_total_cents(data.quantity, price),
        part_number=data.part_number,
        vendor_name=data.vendor_name,
        warranty_months=data.warranty_months,
        warranty_miles=data.warranty_miles,
        warranty_notes=data.warranty_notes,
    )


def copy_line(model: type[LineItemMixin], source: LineItemMixin, position: int):
    line = model(position=position, **{f: getattr(source, f) for f in _COPY_FIELDS})
    line.line_total_cents = line_total_cents(Decimal(line.quantity), line.unit_price_cents)
    return line


def apply_totals(doc: TotalsMixin, items: Sequence[LineItemMixin], tax_rate: Decimal) -> None:
    totals = compute_totals(items, tax_rate)
    doc.tax_rate = tax_rate
    for key, value in totals.as_dict().items():
        setattr(doc, key, value)
