"""The multi-year overview (ticket 57): every Tax Year the ledger touches,
one row per regime — gross, offsets, allowance, taxable and tax — so a
carryforward or a trend is read across years instead of being dug out of
individual reports.

The figures are what the engines state for the ledger as it stands now, not
what a report froze: the overview answers "where do the years stand", a
report answers "what did I file". Each regime is asked year by year through
its own `year_report`, so no rule is restated here — the overview only reads
the columns off each answer.

A year is blocked while a prerequisite is unfinished: every pre-flight
blocker standing open for it (ticket 25), plus whatever an engine itself
refused over that no pre-flight check names. Each carries its reason and the
screen that resolves it. A regime the engine cannot state stays unstated —
never a zero — while the regimes beside it still answer.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import multi_year_overview as overview_repository
from open_leprechaun.services import fx, preflight, section20, section22, section23
from open_leprechaun.services.advance_lump_sums import FundValueUnsetError
from open_leprechaun.services.fx import RateUnavailableError
from open_leprechaun.services.preflight import Blocker
from open_leprechaun.services.section20 import (
    OPENING_CARRYFORWARD_KEYS,
    CarriedCategory,
    TreatyLimitUnsetError,
)
from open_leprechaun.services.section23 import LotShortfallError
from open_leprechaun.services.security_disposals import UnclassifiedSecurityError
from open_leprechaun.services.statutory import StatutoryValueUnsetError, optional_values

__all__ = ["CapitalIncomeYear", "OverviewYear", "RegimeYear", "overview"]


@dataclass(frozen=True)
class RegimeYear:
    """One regime's row for one Tax Year. `gross_eur` is what was gained
    before anything reduced it and `offsets_eur` the losses set against it;
    `allowance_limit_eur` is the year's configured exemption and
    `allowance_eur` what it actually freed. `tax_eur` is None where the rate
    is the Admin's personal one — the taxable amount is the answer there
    (ADR-0007)."""

    gross_eur: Decimal
    offsets_eur: Decimal
    allowance_limit_eur: Decimal
    allowance_eur: Decimal
    taxable_eur: Decimal
    tax_eur: Decimal | None


@dataclass(frozen=True)
class CapitalIncomeYear(RegimeYear):
    """The §20 row with each Verlustverrechnungstopf's carryforward beside
    it: what the pot walked in with, what the year consumed and from which
    year, what the year's loss added, and what walks on — never netted
    across pots, here as anywhere."""

    categories: tuple[CarriedCategory, ...]


@dataclass(frozen=True)
class OverviewYear:
    """One Tax Year across the regimes. A regime is None where its engine
    could not state the year; `blockers` says why, and what else stands
    between the year and a figure fit to finalise."""

    year: int
    blockers: tuple[Blocker, ...]
    private_sales: RegimeYear | None
    other_income: RegimeYear | None
    capital_income: CapitalIncomeYear | None


def overview(
    engine: Engine, source: ReferenceRateSource, *, today: date
) -> tuple[OverviewYear, ...]:
    """Every Tax Year from the first the ledger or an opening carryforward
    touches through the last — and through the current one, which is still
    accruing — oldest first. A ledger with neither has no years."""
    touched = [
        year
        for key in OPENING_CARRYFORWARD_KEYS.values()
        for year in optional_values(engine, key=key)
    ]
    span = overview_repository.activity_span(engine)
    if span is not None:
        touched.extend(fx.event_date(at).year for at in span)
    if not touched:
        return ()
    return tuple(
        _year(engine, source, year) for year in range(min(touched), max(*touched, today.year) + 1)
    )


def _year(engine: Engine, source: ReferenceRateSource, year: int) -> OverviewYear:
    blockers = list(preflight.blockers(engine, year=year))

    def stated[Row](regime: Callable[[], tuple[Row | None, Blocker | None]]) -> Row | None:
        """One regime's row, or None with the reason joining the year's
        blockers — unless a pre-flight check already names the same gap."""
        try:
            row, waiting = regime()
            named_by = _AWAITING.named_by
        except tuple(_REFUSALS) as refusal:
            row = None
            waiting, gap = _refused(refusal)
            named_by = gap.named_by
        named = {blocker.kind for blocker in blockers}
        if waiting is not None and waiting not in blockers and named_by not in named:
            blockers.append(waiting)
        return row

    private_sales = stated(lambda: _private_sales(section23.year_report(engine, source, year=year)))
    other_income = stated(lambda: _other_income(section22.year_report(engine, source, year=year)))
    capital_income = stated(
        lambda: _capital_income(section20.year_report(engine, source, year=year))
    )
    return OverviewYear(
        year=year,
        blockers=tuple(blockers),
        private_sales=private_sales,
        other_income=other_income,
        capital_income=capital_income,
    )


def _private_sales(report: section23.Section23Year) -> tuple[RegimeYear | None, Blocker | None]:
    """§23 as a row: the counted gains, the counted losses set against them,
    and the Freigrenze — all or nothing, so it frees the whole total or none
    of it. The losses are stated in full even where they exceed the gains:
    nothing carries a private-sale loss on here, so the row is the one place
    a losing year shows by how much."""
    verdict = report.freigrenze
    if verdict is None:
        return None, _awaiting("private sale", len(report.awaiting_valuation))
    counted = [
        piece.gain_eur
        for disposal in report.disposals
        for piece in disposal.consumptions
        if piece.gain_eur is not None
        and section23.counts(long_term=piece.long_term, basis_source=piece.basis_source)
    ]
    return RegimeYear(
        gross_eur=sum((gain for gain in counted if gain > 0), Decimal(0)),
        offsets_eur=-sum((gain for gain in counted if gain < 0), Decimal(0)),
        allowance_limit_eur=verdict.limit_eur,
        allowance_eur=_freed(verdict.total_gain_eur, tax_free=verdict.tax_free),
        taxable_eur=verdict.taxable_gain_eur,
        tax_eur=None,
    ), None


def _other_income(report: section22.Section22Year) -> tuple[RegimeYear | None, Blocker | None]:
    """§22 Nr. 3 as a row: the pooled income at market value on receipt —
    nothing offsets it — and its own Freigrenze, all or nothing."""
    verdict = report.freigrenze
    if verdict is None:
        return None, _awaiting("income receipt", len(report.awaiting_valuation))
    return RegimeYear(
        gross_eur=verdict.total_income_eur,
        offsets_eur=Decimal(0),
        allowance_limit_eur=verdict.limit_eur,
        allowance_eur=_freed(verdict.total_income_eur, tax_free=verdict.tax_free),
        taxable_eur=verdict.taxable_income_eur,
        tax_eur=None,
    ), None


def _capital_income(
    report: section20.Section20Year,
) -> tuple[CapitalIncomeYear | None, Blocker | None]:
    """§20 as a row: everything the pots counted as a gain, what losses and
    carryforwards set against it inside each pot, the Sparerpauschbetrag
    applied once across what survived, and — the rate being statutory — the
    tax the flat scheme owes."""
    assessment = report.assessment
    if assessment is None or report.balances is None:
        return None, _awaiting("capital-income event", len(report.awaiting_valuation))
    gross = sum(
        (
            entry.counted_eur
            for balance in report.balances
            for entry in balance.entries
            if entry.counted_eur > 0
        ),
        Decimal(0),
    )
    return CapitalIncomeYear(
        gross_eur=gross,
        offsets_eur=gross - assessment.combined_eur,
        allowance_limit_eur=assessment.allowance_eur,
        allowance_eur=assessment.allowance_applied_eur,
        taxable_eur=assessment.taxable_eur,
        tax_eur=assessment.tax.total_eur,
        categories=assessment.categories,
    ), None


def _freed(total: Decimal, *, tax_free: bool) -> Decimal:
    """What a Freigrenze freed: the whole total while it stays under the
    limit, nothing once it is reached — and nothing where there was no gain
    to free."""
    return total if tax_free and total > 0 else Decimal(0)


@dataclass(frozen=True)
class _Gap:
    """How the overview names one way a regime can go unstated: the blocker
    kind, the screen that resolves it, and the pre-flight check that already
    names the same gap, where one does — that check counts every instance,
    so the engine's first-gap sentence beside it would say the same thing
    twice."""

    kind: str
    resolve_path: str
    named_by: str | None = None


# What an engine may refuse a year over — the same refusals report
# generation answers 409 for (routers/reports.generate_report).
_REFUSALS: dict[type[Exception], _Gap] = {
    StatutoryValueUnsetError: _Gap(
        "statutory_value_unset", "/settings/statutory", "missing_statutory_configuration"
    ),
    FundValueUnsetError: _Gap(
        "fund_value_unset", "/settings/statutory", "missing_advance_lump_sum_inputs"
    ),
    TreatyLimitUnsetError: _Gap("treaty_limit_unset", "/settings/statutory"),
    LotShortfallError: _Gap("lot_shortfall", "/transactions", "lot_shortfalls"),
    UnclassifiedSecurityError: _Gap("unclassified_security", "/instruments", "unclassified_funds"),
    # Nothing the Admin enters closes a gap in the published rates; the
    # system screen is where the source's state is read.
    RateUnavailableError: _Gap("rate_unavailable", "/"),
}

# A price for the event's own day (ADR-0024). The pre-flight's unpriced check
# asks a different question — whether an Instrument was ever priced at all —
# so it never stands in for this one.
_AWAITING = _Gap("awaiting_valuation", "/instruments")


def _refused(refusal: Exception) -> tuple[Blocker, _Gap]:
    """An engine's refusal as a blocker: its own sentence names what stands
    in the way."""
    gap = next(gap for refused, gap in _REFUSALS.items() if isinstance(refusal, refused))
    return Blocker(kind=gap.kind, detail=str(refusal), resolve_path=gap.resolve_path, count=1), gap


def _awaiting(noun: str, count: int) -> Blocker:
    """A regime waiting on a valuation nothing can state yet (ticket 18) —
    the year states no figure rather than netting around the gap."""
    return Blocker(
        kind=_AWAITING.kind,
        detail=(
            f"{count} {noun}{'' if count == 1 else 's'}"
            f" {'awaits' if count == 1 else 'await'} a price for the day of the event."
        ),
        resolve_path=_AWAITING.resolve_path,
        count=count,
    )
