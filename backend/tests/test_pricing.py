from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.core.pricing import compute_totals, line_total_cents, price_from_markup


@dataclass
class L:
    kind: str
    quantity: Decimal
    unit_price_cents: int
    taxable: bool = False


def test_spec_example():
    # Spec §31: 2.0 h x $100 labor + part priced at $120 = $320 subtotal.
    t = compute_totals(
        [L("labor", Decimal("2.0"), 10000), L("part", Decimal("1"), 12000, True)], Decimal("0")
    )
    assert t.subtotal_cents == 32000
    assert t.total_cents == 32000


def test_tax_applies_only_to_taxable_lines():
    t = compute_totals(
        [L("labor", Decimal("2"), 10000), L("part", Decimal("1"), 12000, True)], Decimal("8.875")
    )
    assert t.taxable_cents == 12000
    assert t.tax_cents == 1065  # 12000 * 0.08875 = 1065.0
    assert t.total_cents == 32000 + 1065


def test_rounding_is_half_up_per_line_and_tax():
    assert line_total_cents(Decimal("0.5"), 1) == 1  # 0.5 cent -> 1
    assert line_total_cents(Decimal("1.25"), 9999) == 12499  # 12498.75 -> 12499
    t = compute_totals([L("part", Decimal("1"), 1000, True)], Decimal("6.25"))
    assert t.tax_cents == 63  # 62.5 -> 63


def test_fees_and_discounts():
    t = compute_totals(
        [
            L("labor", Decimal("1"), 10000),
            L("part", Decimal("1"), 5000, True),
            L("fee", Decimal("1"), 1500),
            L("discount", Decimal("1"), 1000, True),  # taxable discount reduces the tax base
        ],
        Decimal("10"),
    )
    assert t.fees_cents == 1500
    assert t.discount_cents == 1000
    assert t.taxable_cents == 4000
    assert t.tax_cents == 400
    assert t.total_cents == 10000 + 5000 + 1500 - 1000 + 400


def test_untaxable_discount_does_not_reduce_tax_base():
    t = compute_totals(
        [L("part", Decimal("1"), 5000, True), L("discount", Decimal("1"), 1000)], Decimal("10")
    )
    assert t.taxable_cents == 5000
    assert t.total_cents == 4000 + 500


def test_discount_cannot_make_total_negative():
    t = compute_totals(
        [L("labor", Decimal("1"), 1000), L("discount", Decimal("1"), 5000)], Decimal("0")
    )
    assert t.total_cents == 0


def test_markup():
    assert price_from_markup(8000, Decimal("50")) == 12000  # spec: $80 cost -> $120
    assert price_from_markup(3333, Decimal("33.33")) == 4444  # 4443.89 -> 4444
    assert price_from_markup(1000, Decimal("0")) == 1000


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
def test_rejects_nonpositive_quantity(bad):
    with pytest.raises(ValueError):
        line_total_cents(bad, 100)


def test_rejects_unknown_kind_and_negative_rate():
    with pytest.raises(ValueError):
        compute_totals([L("bogus", Decimal("1"), 1)], Decimal("0"))
    with pytest.raises(ValueError):
        compute_totals([], Decimal("-1"))
