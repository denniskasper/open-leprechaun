"""The Vorabpauschale (ticket 53, §18 InvStG): the annual advance lump sum a
fund's holder is deemed to have received where the fund distributed less
than a notional minimum return — an amount of income, never a tax.

Per unit, the base yield is the fund's first redemption price of the year
times the Basiszins times the statutory factor (§18 Abs. 1 Satz 2); the
amount is that yield less the year's distributions, floored at zero, then
capped at the year's increase in redemption value (Satz 1 und 3) — zero,
therefore, for a fund that fell. In the year of acquisition the amount goes
down by one twelfth for each full month preceding the month of acquisition
(§18 Abs. 2), which makes it a figure of the Tax Lot: each lot wears its own
acquisition month.

It accrues on the first banking day of the **following** year (§18 Abs. 3)
— so the year it derives from and the year it is declared in are distinct,
and both are named on every record — to whoever holds the units at that
moment: a fund sold during the year produces none.

What was accrued on a lot is deducted from the gain when that lot is sold
(§19 Abs. 1 Satz 3 InvStG), so the same amount is never taxed twice. Accrual
and deduction are one rule read from two sides (`Schedule.lot_amount`): a
lot's amount for a year is its quantity times the year's per-unit amount
times its twelfths, so a partially consumed lot keeps its accumulation
proportionally by construction, and nothing is stored that could drift from
the ledger (ADR-0014). Amounts stay exact; only the engine's Teilfreistellung
split and presentation state cents (services/rounding).

Every input is entered configuration with a cited source: the Basiszins and
the factor per year in the statutory store, the fund's first and last
redemption price and its distributions per fund and year
(repositories/fund_redemption_values). A year with any of them unset refuses
by name — never a market close in a redemption price's place (CONTEXT.md).

What the producer knows ends at the event boundary (ADR-0013): it states
amounts; the engine (services/section20) reduces each to one Section 20
Event wearing the fund's Teilfreistellung rate and alone exempts, nets and
rates.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import fund_redemption_values
from open_leprechaun.repositories.instruments import FUND_TYPES
from open_leprechaun.services import disposals, fx, lots
from open_leprechaun.services.statutory import StatutoryValueUnsetError, required_value

__all__ = [
    "BASE_RATE_KEY",
    "FACTOR_KEY",
    "AdvanceLumpSum",
    "FundValueUnsetError",
    "LotAccrual",
    "PerUnit",
    "Schedule",
    "accrual_date",
    "accruals_through",
    "missing_inputs",
    "per_unit",
    "twelfths_held",
]

BASE_RATE_KEY = "advance_lump_sum_base_rate"
"""The Basiszins in the statutory vocabulary (§18 Abs. 4 InvStG), keyed by
the year the amount derives from."""

FACTOR_KEY = "advance_lump_sum_factor"
"""The share of the Basiszins the base yield uses (§18 Abs. 1 Satz 2
InvStG), keyed like the Basiszins."""

_STATUTES = {BASE_RATE_KEY: "§18 Abs. 4 InvStG", FACTOR_KEY: "§18 Abs. 1 Satz 2 InvStG"}

_MONTHS = 12


class FundValueUnsetError(Exception):
    """A fund was held across a year whose redemption values nobody entered
    — the engine refuses to compute rather than substituting a market close."""


@dataclass(frozen=True)
class PerUnit:
    """One fund's year as the statute computes it for a single unit: the
    entered inputs verbatim, the base yield, and the amount before any
    acquisition-month reduction."""

    start_of_year_eur: Decimal
    end_of_year_eur: Decimal
    distributions_eur: Decimal
    base_rate: Decimal
    factor: Decimal
    base_yield_eur: Decimal
    amount_eur: Decimal


def per_unit(
    *,
    start_of_year_eur: Decimal,
    end_of_year_eur: Decimal,
    distributions_eur: Decimal,
    base_rate: Decimal,
    factor: Decimal,
) -> PerUnit:
    """The rule, pure (§18 Abs. 1 InvStG): base yield less distributions,
    floored at zero, then capped at the year's increase in redemption value
    — in that order — and never below zero, so a fund that fell accrues
    nothing."""
    base_yield = start_of_year_eur * base_rate * factor
    shortfall = max(base_yield - distributions_eur, Decimal(0))
    capped = min(shortfall, end_of_year_eur - start_of_year_eur)
    return PerUnit(
        start_of_year_eur=start_of_year_eur,
        end_of_year_eur=end_of_year_eur,
        distributions_eur=distributions_eur,
        base_rate=base_rate,
        factor=factor,
        base_yield_eur=base_yield,
        amount_eur=max(capped, Decimal(0)),
    )


def twelfths_held(acquired: date, *, year: int) -> int:
    """How many twelfths of the year's amount a unit acquired on this date
    accrues (§18 Abs. 2 InvStG): one goes for each full month preceding the
    month of acquisition, in the year of acquisition alone."""
    if acquired.year < year:
        return _MONTHS
    return _MONTHS - (acquired.month - 1)


def accrual_date(derived_year: int) -> date:
    """When the amount derived from a year counts as received (§18 Abs. 3
    InvStG): the first banking day of the following year — never New Year's
    Day, and the Monday after where 2 January falls on a weekend."""
    day = date(derived_year + 1, 1, 2)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


@dataclass(frozen=True)
class LotAccrual:
    """What one Tax Lot accrued for the year: its acquisition, the quantity
    held at the accrual, the twelfths its acquisition month left it, and the
    amount — quantity x per-unit amount x twelfths / 12."""

    acquired_at: datetime
    quantity: Decimal
    twelfths: int
    amount_eur: Decimal


@dataclass(frozen=True)
class AdvanceLumpSum:
    """One fund's Vorabpauschale in one Depot for one year, naming both
    years the law keeps apart: the one it derives from and the one it is
    declared in. `amount_eur` is before Teilfreistellung — the figure the
    Anlage KAP-INV asks for and the figure a later sale deducts."""

    instrument_id: int
    account_id: int
    derived_year: int
    declared_year: int
    accrued_on: date
    per_unit: PerUnit
    # Where the fund's entered values were taken from, as cited on entry.
    values_source: str
    quantity: Decimal
    amount_eur: Decimal
    lots: tuple[LotAccrual, ...]

    @property
    def source(self) -> str:
        """The record's name in the Section 20 Event vocabulary."""
        return (
            f"advance_lump_sum:{self.derived_year}:account:{self.account_id}"
            f":instrument:{self.instrument_id}"
        )


class Schedule:
    """The entered inputs, read once and asked per fund and year — the one
    place a per-unit amount comes from, for the accrual and for the deduction
    at sale alike."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._rows = {
            (row.instrument_id, row.year): row for row in fund_redemption_values.list_values(engine)
        }
        self._statutory: dict[tuple[int, str], Decimal] = {}
        self._per_unit: dict[tuple[int, int], PerUnit] = {}

    def per_unit(self, instrument: Row, *, year: int) -> PerUnit:
        """The fund's per-unit amount derived from one year. A year whose
        Basiszins, factor or redemption values are unset refuses by name."""
        key = (instrument.id, year)
        if key not in self._per_unit:
            row = self._row(instrument, year)
            self._per_unit[key] = per_unit(
                start_of_year_eur=row.start_of_year_eur,
                end_of_year_eur=row.end_of_year_eur,
                distributions_eur=row.distributions_eur,
                base_rate=self._statutory_value(year, BASE_RATE_KEY),
                factor=self._statutory_value(year, FACTOR_KEY),
            )
        return self._per_unit[key]

    def values_source(self, instrument: Row, *, year: int) -> str:
        return self._row(instrument, year).source

    def lot_amount(
        self, instrument: Row, *, acquired_at: datetime, quantity: Decimal, year: int
    ) -> Decimal:
        """What a quantity acquired at this instant accrues for one year —
        unrounded, so the parts of a split lot sum to the whole to well
        below a cent."""
        twelfths = twelfths_held(fx.event_date(acquired_at), year=year)
        return quantity * self.per_unit(instrument, year=year).amount_eur * twelfths / _MONTHS

    def accumulated(
        self,
        instruments: dict[int, Row],
        instrument_id: int,
        piece: lots.Slice,
        *,
        until: datetime,
    ) -> Decimal:
        """Everything a slice of this Instrument accrued while it was held:
        one amount for each year from its acquisition whose accrual date it
        was still held on — the figure a sale at `until` deducts (§19 Abs. 1
        Satz 3 InvStG). Each year is judged as the slice stood in it
        (`_standing`), so a split since changes no year already accrued.
        Zero, structurally, for everything that was not a fund."""
        total = Decimal(0)
        for year in _accrued_years(fx.event_date(piece.acquired_at), fx.event_date(until)):
            stood = _standing(piece, instrument_id, year=year)
            if stood is None or instruments[stood[0]].type not in FUND_TYPES:
                continue
            total += self.lot_amount(
                instruments[stood[0]], acquired_at=piece.acquired_at, quantity=stood[1], year=year
            )
        return total

    def missing(self, instrument: Row, *, year: int) -> list[str]:
        """What stands unset for this fund's year, named — the statutory keys
        first, then the fund's own row."""
        gaps = []
        for key in (BASE_RATE_KEY, FACTOR_KEY):
            try:
                self._statutory_value(year, key)
            except StatutoryValueUnsetError:
                gaps.append(f"{key} {year}")
        if (instrument.id, year) not in self._rows:
            gaps.append(f"{instrument.symbol} redemption values {year}")
        return gaps

    def _row(self, instrument: Row, year: int) -> Row:
        row = self._rows.get((instrument.id, year))
        if row is None:
            raise FundValueUnsetError(
                f"The {year} redemption values of {instrument.symbol} are unset — enter the"
                " fund's first and last redemption price and its distributions for that"
                " year before its Vorabpauschale can be computed."
            )
        return row

    def _statutory_value(self, year: int, key: str) -> Decimal:
        if (year, key) not in self._statutory:
            self._statutory[(year, key)] = required_value(
                self._engine, year=year, key=key, statute=_STATUTES[key]
            )
        return self._statutory[(year, key)]


def _accrued_years(acquired: date, until: date) -> Iterator[int]:
    """The years a unit acquired on one date and held up to another accrued
    for: each from the acquisition year whose accrual date it reached."""
    year = acquired.year
    while accrual_date(year) <= until:
        yield year
        year += 1


def _standing(piece: lots.Slice, instrument_id: int, *, year: int) -> tuple[int, Decimal] | None:
    """What a slice of this Instrument was at the end of a derived year: the
    Instrument it was units of then and how many — every Corporate Action
    (ticket 52) of a later year undone, because a fund's per-unit values for
    a year are stated in that year's units. None where the slice did not
    exist yet: a spun-off slice inherits its acquisition instant, but what
    accrued before the spin-off accrued on the lot it was taken from.

    An event within the derived year stands: the year closes in the new
    units, so the fund's entered values for that year — its first redemption
    price included — are to be stated in them, as a fund publishes them after
    a split."""
    quantity = piece.quantity
    for change in reversed(piece.changes):
        if fx.event_date(change.at).year <= year:
            break
        if change.born:
            return None
        quantity = quantity * change.units_old / change.units_new
        if change.from_instrument_id is not None:
            instrument_id = change.from_instrument_id
    return instrument_id, quantity


def accruals_through(engine: Engine, *, through_year: int) -> tuple[AdvanceLumpSum, ...]:
    """Every Vorabpauschale declared up to the end of the Tax Year — earlier
    years too, because the engine's carryforward chain nets each of them. One
    record per fund, Depot and derived year, built from the lots held at
    that year's accrual; a fund whose amount is zero still has its record,
    so the working is visible."""
    walked = disposals.replay(engine)
    schedule = Schedule(engine)
    accrued = []
    for (year, account_id, instrument_id), pieces in sorted(
        _held(walked, through_year=through_year).items()
    ):
        instrument = walked.instruments[instrument_id]
        accruals = tuple(
            LotAccrual(
                acquired_at=piece.acquired_at,
                quantity=piece.quantity,
                twelfths=twelfths_held(fx.event_date(piece.acquired_at), year=year),
                amount_eur=schedule.lot_amount(
                    instrument, acquired_at=piece.acquired_at, quantity=piece.quantity, year=year
                ),
            )
            for piece in sorted(pieces, key=lambda piece: piece.acquired_at)
        )
        on = accrual_date(year)
        accrued.append(
            AdvanceLumpSum(
                instrument_id=instrument_id,
                account_id=account_id,
                derived_year=year,
                declared_year=on.year,
                accrued_on=on,
                per_unit=schedule.per_unit(instrument, year=year),
                values_source=schedule.values_source(instrument, year=year),
                quantity=sum((lot.quantity for lot in accruals), Decimal(0)),
                amount_eur=sum((lot.amount_eur for lot in accruals), Decimal(0)),
                lots=accruals,
            )
        )
    return tuple(accrued)


def missing_inputs(engine: Engine, *, through_year: int) -> list[str]:
    """Every input the Vorabpauschalen declared up to the end of the Tax
    Year would need and nobody has entered, each named once — the same
    judgement the producer refuses over, enumerated in full so the pre-flight
    can name every gap instead of failing on the first."""
    walked = disposals.replay(engine)
    schedule = Schedule(engine)
    gaps: dict[str, None] = {}
    for year, _, instrument_id in sorted(_held(walked, through_year=through_year)):
        for gap in schedule.missing(walked.instruments[instrument_id], year=year):
            gaps[gap] = None
    return list(gaps)


def _held(
    walked: disposals.Replay, *, through_year: int
) -> dict[tuple[int, int, int], list[lots.Slice]]:
    """The fund lots held at each accrual declared up to the Tax Year, keyed
    by (derived year, Account, Instrument). The single replay says where
    every unit ended: still in a queue, or finally consumed by a leg on some
    date — a sale, a spend, a fee, a transfer nothing matched. A unit was
    held at an accrual when it was acquired by the end of the derived year
    and not finally consumed before the accrual date; a unit a confirmed
    self-transfer carried was held throughout, in transit or not, and counts
    where it came to rest. Each year holds the unit as it stood then
    (`_standing`): in that year's units, and under the fund it was a unit of
    before any later merger."""
    occurred_at = {row.id: row.occurred_at for row in walked.transaction_rows}
    held: dict[tuple[int, int, int], list[lots.Slice]] = {}

    def hold(account_id: int, instrument_id: int, piece: lots.Slice, gone_on: date | None) -> None:
        for year in range(fx.event_date(piece.acquired_at).year, through_year):
            if gone_on is not None and gone_on < accrual_date(year):
                return
            stood = _standing(piece, instrument_id, year=year)
            if stood is None or walked.instruments[stood[0]].type not in FUND_TYPES:
                continue
            held.setdefault((year, account_id, stood[0]), []).append(
                replace(piece, quantity=stood[1])
            )

    for (account_id, instrument_id), pieces in walked.remaining.items():
        for piece in pieces:
            hold(account_id, instrument_id, piece, None)
    for leg_id, pieces in walked.consumed.items():
        if leg_id in walked.carried_out_leg_ids:
            continue
        leg = walked.leg_by_id[leg_id]
        gone_on = fx.event_date(occurred_at[leg.transaction_id])
        for piece in pieces:
            hold(leg.account_id, leg.instrument_id, piece, gone_on)
    return held
