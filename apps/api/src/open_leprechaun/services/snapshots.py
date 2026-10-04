"""Portfolio snapshots (ticket 54): the portfolio measured, stored once a day
by a scheduled task, and served as a series ending in the live measurement —
so the Admin can see how the portfolio developed without a deposit reading
as a gain.

A measurement states two things about one instant. **Value** is what the
Holdings view totals (services/holdings, ADR-0019): every counted Position,
valued from the store alone — and unstated, never zero, where something is
held and none of it counts. **Contributions** and **withdrawals** are what
crossed the ledger's edge, cumulative from its beginning: value that arrived
from outside — a transfer in that no confirmed self-transfer explains, an
Opening Balance — and value that left for outside — a transfer out nothing
matches, a spend. Everything else is the portfolio's own doing: a trade moves
value between Positions, income and a futures result are what the holdings
earned, a fee is what they cost. Value less contributions plus withdrawals is
therefore the result, however it came about.

A flow is valued as of its own day (ADR-0024) — the numéraire by identity,
foreign cash and stablecoins by the reference rate of the event date, a coin
by the stored close of its day — and an Opening Balance by the estimate the
Admin declared for it, which is what the ledger says the position cost. A
flow nothing stored can value stands outside both sums and is counted, so
the figure names what it leaves out. A flow of a Position that never counts
— ignored, dangerous, unacknowledged — is left out with it: value and
contributions describe the same holdings.

Both figures are stored together because they must describe the same ledger:
a history imported later changes neither side of an old snapshot, and both
sides of the next.

The request path reads the store alone, like Holdings; only the scheduled
task may ask the rate source for a publication the store lacks.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.repositories import snapshots as repository
from open_leprechaun.services import fx, holdings, lots
from open_leprechaun.services.fx import RateUnavailableError
from open_leprechaun.services.rounding import cents
from open_leprechaun.services.stances import effective_stance

__all__ = ["Development", "Measurement", "development", "measure", "take"]

# The types whose legs cross the ledger's edge, and the role that does: what
# arrived is a contribution, what left a withdrawal.
_EDGE_ROLE = {"transfer_in": "in", "opening_balance": "in", "transfer_out": "out", "spend": "out"}


@dataclass(frozen=True)
class Measurement:
    """The portfolio at one instant, filed under its Europe/Berlin date.
    `value_eur` is None where something is held and none of it counts;
    `unvalued_flows` is how many contributions and withdrawals stand outside
    their sums because nothing stored could value them."""

    snapshot_date: date
    taken_at: datetime
    value_eur: Decimal | None
    positions_held: int
    positions_counted: int
    contributions_eur: Decimal
    withdrawals_eur: Decimal
    unvalued_flows: int

    @property
    def net_contributions_eur(self) -> Decimal:
        return self.contributions_eur - self.withdrawals_eur

    @property
    def result_eur(self) -> Decimal | None:
        """What the holdings did, apart from what was put in and taken out."""
        return None if self.value_eur is None else self.value_eur - self.net_contributions_eur


@dataclass(frozen=True)
class Development:
    """The stored series, oldest first, and the portfolio as it stands now."""

    snapshots: tuple[Measurement, ...]
    current: Measurement


def measure(
    engine: Engine, source: ReferenceRateSource | None = None, *, now: datetime
) -> Measurement:
    """The portfolio as it stands. Without a rate source nothing outside the
    store is consulted; with one — the scheduled task's — a publication the
    store lacks is fetched and kept, so later reads find it."""
    positions = holdings.portfolio(engine)
    counted = [position for position in positions if position.marker is None]
    contributions, withdrawals, unvalued = _flows(engine, source)
    return Measurement(
        snapshot_date=fx.event_date(now),
        taken_at=now,
        value_eur=(
            sum((position.value_eur for position in counted), cents(Decimal(0)))
            if counted or not positions
            else None
        ),
        positions_held=len(positions),
        positions_counted=len(counted),
        contributions_eur=contributions,
        withdrawals_eur=withdrawals,
        unvalued_flows=unvalued,
    )


def take(engine: Engine, source: ReferenceRateSource, *, now: datetime) -> Measurement:
    """Measure and store: the day's snapshot, replacing an earlier one of the
    same Europe/Berlin date."""
    measured = measure(engine, source, now=now)
    repository.store(engine, **vars(measured))
    return measured


def development(engine: Engine, *, now: datetime) -> Development:
    return Development(
        snapshots=tuple(Measurement(**row._mapping) for row in repository.list_snapshots(engine)),
        current=measure(engine, now=now),
    )


def _flows(engine: Engine, source: ReferenceRateSource | None) -> tuple[Decimal, Decimal, int]:
    """Cumulative contributions and withdrawals over the whole ledger, and
    how many flows stand outside them unvalued."""
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        stance_rows = lots_repository.stance_rows(connection)
        match_rows = lots_repository.match_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
    instruments = {row.id: row for row in instrument_rows}
    decisions_of = lots.grouped(stance_rows, "instrument_id")
    legs_of = lots.grouped(leg_rows, "transaction_id")
    # Both ends of a confirmed self-transfer stayed inside the ledger.
    internal = {leg_id for match in match_rows for leg_id in (match.out_leg_id, match.in_leg_id)}

    totals = {"in": cents(Decimal(0)), "out": cents(Decimal(0))}
    unvalued = 0
    for transaction in transaction_rows:
        role = _EDGE_ROLE.get(transaction.type)
        if role is None:
            continue
        for leg in legs_of.get(transaction.id, []):
            if leg.role != role or leg.id in internal:
                continue
            instrument = instruments[leg.instrument_id]
            if not instrument.is_numeraire and (
                effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id) != "kept"
            ):
                continue
            value = _flow_value(engine, source, transaction, leg, instrument)
            if value is None:
                unvalued += 1
            else:
                totals[role] += cents(value)
    return totals["in"], totals["out"], unvalued


def _flow_value(
    engine: Engine,
    source: ReferenceRateSource | None,
    transaction: Row,
    leg: Row,
    instrument: Row,
) -> Decimal | None:
    if transaction.type == "opening_balance":
        # One position per Opening Balance, so the declared estimate is this
        # leg's whole cost — what the ledger says was put in.
        return transaction.estimated_basis_eur
    at = transaction.occurred_at
    if source is None:
        return fx.stored_value_eur(engine, instrument=instrument, quantity=leg.quantity, at=at)
    try:
        return fx.value_eur(engine, source, instrument=instrument, quantity=leg.quantity, at=at)
    except RateUnavailableError:
        return None
