"""Pre-flight blockers (ticket 25): what the application already knows is
wrong, asked once more at the moment the Admin tries to finalise a report —
the last moment a problem is still cheap to fix. Each blocker is one
condition, aggregated with a count, a sentence naming what stands in the
way, and the path of the screen that resolves it.

The registry is the extension point: a later ticket that learns a new way a
report can be wrong adds one check function to CHECKS and the finalisation
flow (services/reports.finalise) never changes. A check answers for one
report year — it judges what could move that year's figures, not everything
the ledger will ever hold.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from open_leprechaun.repositories import crypto_prices
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import instruments as instruments_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.repositories import preflight as preflight_repository
from open_leprechaun.services import disposals, fx, lots, statutory, transfer_matches
from open_leprechaun.services.stances import effective_stance, never_enters_cost_basis

__all__ = ["CHECKS", "Blocker", "blockers"]


@dataclass(frozen=True)
class Blocker:
    """One reason finalisation must wait: what kind of problem, a sentence
    naming it, how many instances stand open, and the screen that resolves
    it."""

    kind: str
    detail: str
    resolve_path: str
    count: int


def _lot_shortfalls(engine: Engine, year: int) -> Blocker | None:
    """Disposals up to the end of the report's year that exceed the lots
    their Accounts hold — an acquisition is missing from the ledger, and
    every later consumption's FIFO position rests on the gap. The judgement
    is the disposal walk's own (services/disposals.lot_shortfalls), covering
    every lot-consuming family — the engines refuse over the first such gap;
    a pre-flight names them all."""
    short = disposals.lot_shortfalls(engine, through_year=year)
    if not short:
        return None
    symbols = ", ".join(sorted(set(short)))
    return Blocker(
        kind="lot_shortfalls",
        detail=(
            f"{_count(len(short), 'disposal')} up to the end of {year}"
            f" {'exceeds' if len(short) == 1 else 'exceed'} the lots"
            f" {'its Account holds' if len(short) == 1 else 'their Accounts hold'}"
            f" — an acquisition is missing from the ledger: {symbols}."
        ),
        resolve_path="/transactions",
        count=len(short),
    )


def _unacknowledged_instruments(engine: Engine, year: int) -> Blocker | None:
    """Arrivals up to the end of the report's year that nobody has classified
    — each waits in the inbox, and an unclassified inflow mints no Tax Lot,
    so the figures cannot yet be honest about it (ADR-0012)."""
    arrivals = preflight_repository.unacknowledged_arrivals(engine, year=year)
    if not arrivals:
        return None
    symbols = ", ".join(sorted({arrival.symbol for arrival in arrivals}))
    return Blocker(
        kind="unacknowledged_instruments",
        detail=(
            f"{_count(len(arrivals), 'unacknowledged arrival')} up to the end of"
            f" {year} {'waits' if len(arrivals) == 1 else 'wait'} in the inbox:"
            f" {symbols}."
        ),
        resolve_path="/inbox",
        count=len(arrivals),
    )


def _missing_statutory_configuration(engine: Engine, year: int) -> Blocker | None:
    """Required statutory values the year has no row for — a report resting
    on an unset constant cannot honestly finalise."""
    missing = statutory.missing_for_year(engine, year)
    if not missing:
        return None
    return Blocker(
        kind="missing_statutory_configuration",
        detail=(
            f"The {year} statutory configuration is missing required values: {', '.join(missing)}."
        ),
        resolve_path="/settings/statutory",
        count=len(missing),
    )


def _unmatched_transfers(engine: Engine, year: int) -> Blocker | None:
    """Transfer legs no confirmed match carries, up to the end of the
    report's year — each one is cost basis that vanished or appeared without
    an explanation, and the year's FIFO rests on the answer. A later year's
    transfer cannot move this year's figures and does not block; a leg
    standing ignored or dangerous never enters the cost basis (ADR-0012), so
    it has nothing to explain and does not block either."""
    overview = transfer_matches.matching_overview(engine)
    with engine.connect() as connection:
        decisions_of = lots.grouped(lots_repository.stance_rows(connection), "instrument_id")
    unmatched = [
        leg
        for leg in overview.unmatched_outgoing + overview.unmatched_incoming
        if fx.event_date(leg.occurred_at).year <= year
        and not never_enters_cost_basis(
            effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
        )
    ]
    if not unmatched:
        return None
    return Blocker(
        kind="unmatched_transfers",
        detail=(
            f"{_count(len(unmatched), 'transfer leg')} up to the end of {year}"
            f" {'awaits' if len(unmatched) == 1 else 'await'} a confirmed match."
        ),
        resolve_path="/transfers",
        count=len(unmatched),
    )


def _unpriced_instruments(engine: Engine, year: int) -> Blocker | None:
    """Instruments the price chain answers for (ticket 18) that nothing has
    ever priced, moving in the report's year — a figure resting on one would
    wait on a valuation, never a zero."""
    active = preflight_repository.active_instrument_ids(engine, year=year)
    unpriced = [
        instrument
        for instrument in crypto_prices.priceable_instruments(engine)
        if instrument.id in active and crypto_prices.last_known(engine, instrument.id) is None
    ]
    if not unpriced:
        return None
    symbols = ", ".join(instrument.symbol for instrument in unpriced)
    return Blocker(
        kind="unpriced_instruments",
        detail=(
            f"{_count(len(unpriced), 'Instrument')} with activity in {year}"
            f" {'has' if len(unpriced) == 1 else 'have'} never been priced: {symbols}."
        ),
        resolve_path="/instruments",
        count=len(unpriced),
    )


def _unattributable_funding(engine: Engine, year: int) -> Blocker | None:
    """Funding payments up to the end of the report's year that no single
    position could claim (ticket 28) — surfaced, never dropped: each is part
    of some position's net figure, so a report over them would understate or
    overstate a Termingeschäfte result."""
    payments = preflight_repository.unattributable_funding(engine, year=year)
    if not payments:
        return None
    symbols = ", ".join(sorted({payment.symbol for payment in payments}))
    return Blocker(
        kind="unattributable_funding",
        detail=(
            f"{_count(len(payments), 'funding payment')} up to the end of {year}"
            f" {'belongs' if len(payments) == 1 else 'belong'} to no position:"
            f" {symbols}."
        ),
        resolve_path="/futures",
        count=len(payments),
    )


def _futures_derivation_issues(engine: Engine, year: int) -> Blocker | None:
    """Fill streams the derivation refused to guess at (ADR-0009). Not
    bounded by the year: a stream whose opening fills predate what its
    source returned could move any year's figures, so every report waits on
    the manual handling."""
    with engine.connect() as connection:
        issues = futures_repository.issue_rows(connection)
    if not issues:
        return None
    symbols = ", ".join(sorted({issue.symbol for issue in issues}))
    return Blocker(
        kind="futures_derivation_issues",
        detail=(
            f"{_count(len(issues), 'futures fill stream')} could not be"
            f" reconciled into positions and"
            f" {'awaits' if len(issues) == 1 else 'await'} manual handling:"
            f" {symbols}."
        ),
        resolve_path="/futures",
        count=len(issues),
    )


def _unclassified_funds(engine: Engine, year: int) -> Blocker | None:
    """Funds in the ledger up to the end of the report's year whose
    Teilfreistellung category nothing has stated — and securities still typed
    `unknown`, which cannot yet say whether they are funds. Bounded by
    holding, not in-year trading: a fund merely held still accrues
    Vorabpauschale. A figure over either would have to assume an exemption,
    and the app refuses to assume (ticket 44); the direct action is
    classifying them on the Instruments screen."""
    unclassified = instruments_repository.unclassified_funds(engine, through_year=year)
    if not unclassified:
        return None
    symbols = ", ".join(fund.symbol for fund in unclassified)
    return Blocker(
        kind="unclassified_funds",
        detail=(
            f"{_count(len(unclassified), 'fund')} in the ledger up to the end of {year}"
            f" {'carries' if len(unclassified) == 1 else 'carry'} no Teilfreistellung"
            f" classification: {symbols}."
        ),
        resolve_path="/instruments",
        count=len(unclassified),
    )


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


Check = Callable[[Engine, int], Blocker | None]

CHECKS: tuple[Check, ...] = (
    _unmatched_transfers,
    _unpriced_instruments,
    _unclassified_funds,
    _lot_shortfalls,
    _unacknowledged_instruments,
    _unattributable_funding,
    _futures_derivation_issues,
    _missing_statutory_configuration,
)
"""Every registered pre-flight check. A later ticket registers a further
blocker by appending its check here — the finalisation flow reads only this
tuple and never changes."""


def blockers(engine: Engine, *, year: int) -> tuple[Blocker, ...]:
    """Everything standing in the way of finalising this year's report, in
    the registry's order — empty means nothing known is wrong."""
    return tuple(blocker for check in CHECKS if (blocker := check(engine, year)) is not None)
