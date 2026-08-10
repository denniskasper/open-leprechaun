"""The one rounding rule.

Euro amounts are rounded **half-even to the cent** (`ROUND_HALF_EVEN` — no
upward bias), and only at two kinds of boundary:

- **statutory boundaries** — where a statute makes an amount real: a
  pro-rated share of proceeds, costs or basis, a Teilfreistellung split, a
  tax amount from a rate. Splitting one exact amount rounds every share but
  the last and leaves the exact remainder on it, so no cent is invented or
  lost;
- **presentation** — where a figure is shown or exported. The stored figure
  stays exact; only its rendering states cents.

One named exception: a per-unit *price* below one euro keeps eight fraction
digits at presentation (`per_unit`), because a cent would round a
micro-priced token's whole answer away. It applies to prices alone, never to
an amount.

Everything in between — sums, differences, conversions — is exact `Decimal`
arithmetic. Nothing else rounds: a `quantize` anywhere outside this module
is a defect. Quantities are not euro amounts and are never rounded at all.
"""

from decimal import ROUND_HALF_EVEN, Decimal

__all__ = ["CENT", "cents", "per_unit"]

CENT = Decimal("0.01")

_FINE = Decimal("1E-8")


def cents(amount: Decimal) -> Decimal:
    """The amount stated in cents, half-even — the one rounding this
    application performs on a euro amount."""
    return amount.quantize(CENT, ROUND_HALF_EVEN)


def per_unit(price: Decimal) -> Decimal:
    """A per-unit price for presentation: cents, except below one euro,
    where eight fraction digits keep a micro-priced token's answer."""
    fine = price != 0 and abs(price) < 1
    return price.quantize(_FINE if fine else CENT, ROUND_HALF_EVEN)
