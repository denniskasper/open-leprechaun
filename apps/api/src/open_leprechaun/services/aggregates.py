"""Aggregates: bots and dust sweeps (ticket 30). Two cases where thousands
of tiny records would otherwise drown the ledger — a bot-run strategy's
futures activity, and a venue sweeping many dust balances into one coin —
are each summarised as one Aggregate whose constituents remain retrievable.

An Aggregate is presentation only. Its figures are sums over its
constituents, never recomputations, so summarising cannot change a number;
the tax engines never read it — every constituent position still emits its
own Section 20 Event and every constituent disposal still consumes its own
lots — and membership sits outside the input fingerprint (ADR-0014) like a
note, so tagging marks no report stale. No record is suppressed from any
total, only collapsed in the summary presentation.

A bot aggregate is a scope, not a member list: it names the fill source it
summarises — optionally narrowed to one symbol — because derived positions
are wiped and rebuilt wholesale per source (ADR-0009), and the scope is what
survives the rebuild. A dust sweep's members are the constituent trade
Transactions themselves, judged homogeneous on recording: each exchanges
dust for the one received Instrument at the one Account the sweep arrived
at.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import aggregates as repository
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.services import futures as futures_service
from open_leprechaun.services import transactions as transactions_service
from open_leprechaun.services.futures import PositionOverview
from open_leprechaun.services.transactions import TransactionOverview

__all__ = [
    "AggregatesOverview",
    "BotConstituents",
    "BotSummary",
    "DustSweepConstituents",
    "DustSweepSummary",
    "FillOverview",
    "SettlementTotals",
    "constituents",
    "disband",
    "overview",
    "record_bot",
    "record_dust_sweep",
]


@dataclass(frozen=True)
class SettlementTotals:
    """One settlement currency's sums over an aggregate's closed positions —
    each component the sum of what the constituents state separately, and
    `net` the very figure their emissions carry into the Termingeschäfte
    pot, so the summary can never disagree with the report."""

    settlement_instrument_id: int
    realized: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal


@dataclass(frozen=True)
class BotSummary:
    """A bot-run strategy's activity as one line: what the scope's fills
    derived, counted and summed — never recomputed from aggregate-level
    entry and exit."""

    id: int
    label: str
    source: str
    symbol: str | None
    fill_count: int
    open_positions: int
    closed_positions: int
    closed_totals: tuple[SettlementTotals, ...]


@dataclass(frozen=True)
class DustSweepSummary:
    """One aggregate disposal into the received Instrument. Derived from the
    members as the ledger holds them now: where later edits made them
    disagree on what arrived where, the received side is stated as nothing
    rather than as one member's answer."""

    id: int
    label: str
    constituent_count: int
    received_account_id: int | None
    received_instrument_id: int | None
    received_quantity: Decimal | None
    first_occurred_at: datetime | None
    last_occurred_at: datetime | None


@dataclass(frozen=True)
class AggregatesOverview:
    bots: tuple[BotSummary, ...]
    dust_sweeps: tuple[DustSweepSummary, ...]


@dataclass(frozen=True)
class FillOverview:
    """One constituent fill as stored — the immutable record behind a bot's
    summary."""

    id: int
    source: str
    external_id: str
    account_id: int
    symbol: str
    side: str
    price: Decimal
    size: Decimal
    fee: Decimal
    settlement_instrument_id: int
    occurred_at: datetime
    position_side: str | None
    reduce_only: bool | None
    realized: Decimal | None
    inverse: bool | None


@dataclass(frozen=True)
class BotConstituents:
    summary: BotSummary
    fills: tuple[FillOverview, ...]
    positions: tuple[PositionOverview, ...]


@dataclass(frozen=True)
class DustSweepConstituents:
    summary: DustSweepSummary
    transactions: tuple[TransactionOverview, ...]


def record_bot(engine: Engine, *, label: str, source: str, symbol: str | None = None) -> int | str:
    """Draw a bot aggregate over a fill source — or the sentence naming why
    not. Overlapping scopes are refused: two summaries over one stream would
    present its figures twice."""
    with engine.begin() as connection:
        standing = repository.overlapping_bot_scope(connection, source=source, symbol=symbol)
        if standing is not None:
            return (
                f"The bot aggregate {standing.label!r} already summarises this scope —"
                " one summary per stream; disband it first."
            )
        return repository.insert_bot(connection, label=label, source=source, symbol=symbol)


def record_dust_sweep(engine: Engine, *, label: str, transaction_ids: Sequence[int]) -> int | str:
    """Record a dust sweep over its constituent trades — or the sentence
    naming why the set is not one sweep. Each constituent must be a trade
    arriving as exactly one in-leg, all in the one received Instrument at
    the one Account, and belong to no other aggregate."""
    ids = list(dict.fromkeys(transaction_ids))
    with engine.begin() as connection:
        candidates = repository.constituent_candidates(connection, ids)
        defect = _sweep_defect(ids, candidates)
        if defect is not None:
            return defect
        aggregate_id = repository.insert_dust_sweep(connection, label=label)
        repository.tag_transactions(connection, aggregate_id, ids)
        return aggregate_id


def _sweep_defect(ids: list[int], candidates: list[Row]) -> str | None:
    found = {row.id for row in candidates}
    if found != set(ids):
        return "A dust sweep names a Transaction the ledger does not hold."
    if any(row.type != "trade" for row in candidates):
        return (
            "Only trades form a dust sweep — each constituent exchanges dust"
            " for the received Instrument."
        )
    if any(row.aggregate_id is not None for row in candidates):
        return "A Transaction already belongs to another aggregate."
    in_legs_of: dict[int, list[Row]] = {}
    for row in candidates:
        if row.leg_id is not None:
            in_legs_of.setdefault(row.id, []).append(row)
    if any(len(in_legs_of.get(transaction_id, [])) != 1 for transaction_id in ids):
        return "A dust sweep constituent receives exactly one in-leg."
    received = {(legs[0].account_id, legs[0].instrument_id) for legs in in_legs_of.values()}
    if len(received) > 1:
        return "A dust sweep arrives in one Instrument at one Account — these trades disagree."
    return None


def disband(engine: Engine, aggregate_id: int) -> bool:
    """Remove the summary, never the summarised: members are released, fills
    and Transactions stand exactly as before."""
    return repository.delete(engine, aggregate_id)


def overview(engine: Engine) -> AggregatesOverview:
    """Every aggregate as one summary line, on one connection — the
    presentation the constituents collapse into, every figure a sum over
    them."""
    with engine.connect() as connection:
        aggregate_rows = repository.rows(connection)
        fill_counts = repository.fill_counts(connection)
        position_rows = futures_repository.position_rows(connection)
        member_rows = repository.sweep_member_rows(connection)
    bots = tuple(
        _bot_summary(row, fill_counts, position_rows) for row in aggregate_rows if row.kind == "bot"
    )
    members_of: dict[int, list[Row]] = {}
    for member in member_rows:
        members_of.setdefault(member.aggregate_id, []).append(member)
    sweeps = tuple(
        _sweep_summary(row, members_of.get(row.id, []))
        for row in aggregate_rows
        if row.kind == "dust_sweep"
    )
    return AggregatesOverview(bots=bots, dust_sweeps=sweeps)


def constituents(
    engine: Engine, aggregate_id: int
) -> BotConstituents | DustSweepConstituents | None:
    """One aggregate's constituents, retrievable in full: a bot's stored
    fills and the positions they derived; a sweep's member Transactions with
    their legs. None where no aggregate has the id."""
    with engine.connect() as connection:
        row = repository.get(connection, aggregate_id)
    if row is None:
        return None
    if row.kind == "bot":
        return _bot_constituents(engine, row)
    return _sweep_constituents(engine, row)


def _bot_constituents(engine: Engine, row: Row) -> BotConstituents:
    with engine.connect() as connection:
        fill_rows = repository.fills_for_scope(
            connection, source=row.futures_source, symbol=row.futures_symbol
        )
        fill_counts = repository.fill_counts(connection)
        position_rows = futures_repository.position_rows(connection)
    return BotConstituents(
        summary=_bot_summary(row, fill_counts, position_rows),
        fills=tuple(FillOverview(**fill._mapping) for fill in fill_rows),
        positions=tuple(
            position
            for position in futures_service.overview(engine).positions
            if position.aggregate_id == row.id
        ),
    )


def _sweep_constituents(engine: Engine, row: Row) -> DustSweepConstituents:
    with engine.connect() as connection:
        members = [
            member
            for member in repository.sweep_member_rows(connection)
            if member.aggregate_id == row.id
        ]
    wanted = {member.id for member in members}
    return DustSweepConstituents(
        summary=_sweep_summary(row, members),
        transactions=tuple(
            transaction
            for transaction in transactions_service.overview(engine)
            if transaction.id in wanted
        ),
    )


def _bot_summary(row: Row, fill_counts: list[Row], position_rows: list[Row]) -> BotSummary:
    covered = [
        position
        for position in position_rows
        if repository.scope_covers(
            scope_source=row.futures_source,
            scope_symbol=row.futures_symbol,
            source=position.source,
            symbol=position.symbol,
        )
    ]
    closed = [position for position in covered if position.closed_at is not None]
    totals: dict[int, dict[str, Decimal]] = {}
    for position in closed:
        sums = totals.setdefault(
            position.settlement_instrument_id,
            {"realized": Decimal(0), "fees": Decimal(0), "funding": Decimal(0)},
        )
        sums["realized"] += position.realized
        sums["fees"] += position.fees
        sums["funding"] += position.funding
    return BotSummary(
        id=row.id,
        label=row.label,
        source=row.futures_source,
        symbol=row.futures_symbol,
        fill_count=sum(
            counted.fills
            for counted in fill_counts
            if repository.scope_covers(
                scope_source=row.futures_source,
                scope_symbol=row.futures_symbol,
                source=counted.source,
                symbol=counted.symbol,
            )
        ),
        open_positions=len(covered) - len(closed),
        closed_positions=len(closed),
        closed_totals=tuple(
            SettlementTotals(
                settlement_instrument_id=settlement,
                realized=sums["realized"],
                fees=sums["fees"],
                funding=sums["funding"],
                net=sums["realized"] - sums["fees"] + sums["funding"],
            )
            for settlement, sums in sorted(totals.items())
        ),
    )


def _sweep_summary(row: Row, members: list[Row]) -> DustSweepSummary:
    ids = {member.id for member in members}
    # One row per in-leg: the sweep was judged homogeneous — one in-leg per
    # trade, one destination — when it was recorded, but a member edited
    # since may no longer fit, and then the received side is honestly
    # nothing rather than one member's answer.
    legged = [member for member in members if member.instrument_id is not None]
    received = {(member.account_id, member.instrument_id) for member in legged}
    agreed = len(received) == 1 and len(legged) == len(ids)
    account_id, instrument_id = next(iter(received)) if agreed else (None, None)
    instants = [member.occurred_at for member in members]
    return DustSweepSummary(
        id=row.id,
        label=row.label,
        constituent_count=len(ids),
        received_account_id=account_id,
        received_instrument_id=instrument_id,
        received_quantity=(
            sum((member.quantity for member in legged), Decimal(0)) if agreed else None
        ),
        first_occurred_at=min(instants) if instants else None,
        last_occurred_at=max(instants) if instants else None,
    )
