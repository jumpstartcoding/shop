"""The one place money is calculated.

Every estimate, work order, and invoice total comes from compute_totals(). All amounts are
integer cents; quantities and rates are Decimals; rounding is half-up, once per line and
once for tax.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

CENT = Decimal("1")
HUNDRED = Decimal("100")


def round_cents(value: Decimal) -> int:
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def line_total_cents(quantity: Decimal, unit_price_cents: int) -> int:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if unit_price_cents < 0:
        raise ValueError("unit price cannot be negative")
    return round_cents(Decimal(quantity) * Decimal(unit_price_cents))


def price_from_markup(unit_cost_cents: int, markup_pct: Decimal) -> int:
    """Customer price for a part given its cost and a markup percentage (50 means +50%)."""
    if unit_cost_cents < 0:
        raise ValueError("cost cannot be negative")
    if markup_pct < 0:
        raise ValueError("markup cannot be negative")
    return round_cents(Decimal(unit_cost_cents) * (HUNDRED + Decimal(markup_pct)) / HUNDRED)


class PricedLine(Protocol):
    kind: str
    quantity: Decimal
    unit_price_cents: int
    taxable: bool


@dataclass(frozen=True)
class Totals:
    labor_cents: int
    parts_cents: int
    fees_cents: int
    discount_cents: int
    taxable_cents: int
    tax_cents: int
    total_cents: int

    @property
    def subtotal_cents(self) -> int:
        """Labor + parts, before fees, discounts, and tax."""
        return self.labor_cents + self.parts_cents

    def as_dict(self) -> dict[str, int]:
        return {
            "labor_cents": self.labor_cents,
            "parts_cents": self.parts_cents,
            "fees_cents": self.fees_cents,
            "discount_cents": self.discount_cents,
            "taxable_cents": self.taxable_cents,
            "tax_cents": self.tax_cents,
            "total_cents": self.total_cents,
        }


def compute_totals(lines: Iterable[PricedLine], tax_rate_pct: Decimal) -> Totals:
    """Totals for a document.

    taxable base = taxable labor/parts/fees minus taxable discounts, floored at zero.
    A discount marked taxable reduces the taxable base; an untaxable one only reduces the total.
    The total is floored at zero: discounts can't make the shop owe the customer.
    """
    if tax_rate_pct < 0:
        raise ValueError("tax rate cannot be negative")

    sums = {"labor": 0, "part": 0, "fee": 0, "discount": 0}
    taxable_charges = 0
    taxable_discounts = 0
    for line in lines:
        if line.kind not in sums:
            raise ValueError(f"unknown line kind: {line.kind}")
        amount = line_total_cents(Decimal(line.quantity), line.unit_price_cents)
        sums[line.kind] += amount
        if line.taxable:
            if line.kind == "discount":
                taxable_discounts += amount
            else:
                taxable_charges += amount

    taxable = max(taxable_charges - taxable_discounts, 0)
    tax = round_cents(Decimal(taxable) * Decimal(tax_rate_pct) / HUNDRED)
    pre_tax = sums["labor"] + sums["part"] + sums["fee"] - sums["discount"]
    total = max(pre_tax, 0) + tax

    return Totals(
        labor_cents=sums["labor"],
        parts_cents=sums["part"],
        fees_cents=sums["fee"],
        discount_cents=sums["discount"],
        taxable_cents=taxable,
        tax_cents=tax,
        total_cents=total,
    )
