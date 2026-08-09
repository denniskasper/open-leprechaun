"""Futures fills, positions and funding (ticket 28, ADR-0009).

Imported fills are stored immutably, deduplicated on source and external
identifier, and positions are derived as a pure function of the *entire*
ordered fill sequence — rebuilt wholesale per source on every sync, never
patched incrementally, so overlapping windows and repeated runs cannot
double-count. Manually entered and derived positions share one row shape and
one tax treatment; only their origin differs.

A stream is one account's fills for one symbol — split further by position
side where the venue states it, because a hedge-mode long and short run
concurrently and netting them would erase both. Within a stream the
documented net accounting applies: an extension averages the entry price, a
reduction realises against that average, and a fill crossing zero closes one
position and opens the next with the remainder, its fee split pro rata.
Where the venue states a fill's own realised result it is used verbatim, and
reduce-only rules a flip out. A stream the flags contradict — a reduce-only
fill with nothing open, a hedge-stream reduction beyond what is open — is
withdrawn whole and flagged as an issue for manual handling rather than
guessed at (ADR-0009).

Funding is pulled separately and attributed to the position open for its
account and symbol at the payment instant; a payment no single position can
claim — none open, or a hedge-mode pair both open — stays stored with no
attribution and is surfaced as unattributable, never dropped.

The tax treatment lives elsewhere: a closed position emits one Section 20
Event in the termingeschaefte pot (services/section20), and this module
computes no tax of its own (ADR-0013).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Connection, Engine, Row
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import futures as repository
from open_leprechaun.repositories.futures import (
    DerivationIssue,
    FuturesPosition,
    NormalizedFill,
    NormalizedFunding,
    Refusal,
)

__all__ = [
    "Derivation",
    "DerivationIssue",
    "FundingOverview",
    "FuturesOverview",
    "FuturesPosition",
    "IssueOverview",
    "NormalizedFill",
    "NormalizedFunding",
    "PositionOverview",
    "Refusal",
    "SyncResult",
    "delete_manual_position",
    "derive",
    "net_figure",
    "overview",
    "rebuild",
    "record_manual_position",
    "replace_manual_position",
    "sync",
]


@dataclass(frozen=True)
class Derivation:
    positions: tuple[FuturesPosition, ...]
    issues: tuple[DerivationIssue, ...]


_DIRECTION = {"long": 1, "short": -1}


def derive(fills: Iterable[NormalizedFill | Row]) -> Derivation:
    """The pure reconstruction: the entire fill sequence in, positions and
    issues out — fed a port's normalized fills or the stored rows alike,
    which share their field names. Deterministic over the set of fills —
    input order never matters, only each fill's own instant (ties keep the
    given order, all a venue's export lets anyone promise)."""
    streams: dict[tuple[int, str, str | None], list[NormalizedFill | Row]] = {}
    for fill in fills:
        streams.setdefault((fill.account_id, fill.symbol, fill.position_side), []).append(fill)
    positions: list[FuturesPosition] = []
    issues: list[DerivationIssue] = []
    for key in sorted(streams, key=lambda key: (key[0], key[1], key[2] or "")):
        derived, issue = _walk(streams[key], *key)
        if issue is not None:
            issues.append(issue)
        else:
            positions.extend(derived)
    positions.sort(key=lambda position: (position.opened_at, position.symbol, position.side))
    return Derivation(positions=tuple(positions), issues=tuple(issues))


def _walk(
    fills: list[NormalizedFill | Row], account_id: int, symbol: str, position_side: str | None
) -> tuple[list[FuturesPosition], DerivationIssue | None]:
    """One stream walked in time order under net accounting. `forced` is the
    hedge-mode direction where the venue stated one — a stream that can
    never flip."""
    forced = _DIRECTION[position_side] if position_side is not None else None

    def issue(reason: str) -> tuple[list[FuturesPosition], DerivationIssue]:
        return [], DerivationIssue(
            account_id=account_id, symbol=symbol, position_side=position_side, reason=reason
        )

    positions: list[FuturesPosition] = []
    pos = Decimal(0)
    avg = Decimal(0)
    opened_at: datetime | None = None
    settlement: int | None = None
    total_opened = Decimal(0)
    realized = Decimal(0)
    fees = Decimal(0)
    for fill in sorted(fills, key=lambda fill: fill.occurred_at):
        delta = fill.size if fill.side == "buy" else -fill.size
        extends = _sign(delta) == (forced or _sign(pos)) if pos != 0 or forced else True
        if extends:
            if fill.reduce_only:
                return issue(
                    "A reduce-only fill would open or extend a position — its"
                    " opening fills predate what the source returned."
                )
            if pos == 0:
                opened_at = fill.occurred_at
                settlement = fill.settlement_instrument_id
            avg = (avg * abs(pos) + fill.price * fill.size) / (abs(pos) + fill.size)
            pos += delta
            total_opened += fill.size
            fees += fill.fee
            continue
        direction = _sign(pos)
        reduced = min(fill.size, abs(pos))
        remainder = fill.size - reduced
        if remainder and forced is not None:
            return issue(
                "A reduction exceeds the open position — its opening fills"
                " predate what the source returned."
            )
        if remainder and fill.reduce_only:
            return issue(
                "A reduce-only fill exceeds the open position — its opening"
                " fills predate what the source returned."
            )
        realized += (
            fill.realized if fill.realized is not None else (fill.price - avg) * reduced * direction
        )
        fees += fill.fee * reduced / fill.size
        pos -= direction * reduced
        if pos == 0:
            positions.append(
                _position(
                    account_id=account_id,
                    symbol=symbol,
                    direction=direction,
                    quantity=total_opened,
                    settlement=settlement,
                    opened_at=opened_at,
                    closed_at=fill.occurred_at,
                    realized=realized,
                    fees=fees,
                )
            )
            avg, total_opened, realized, fees = Decimal(0), Decimal(0), Decimal(0), Decimal(0)
            opened_at = None
            if remainder:
                opened_at = fill.occurred_at
                settlement = fill.settlement_instrument_id
                avg = fill.price
                pos = -direction * remainder
                total_opened = remainder
                fees = fill.fee * remainder / fill.size
    if pos != 0:
        positions.append(
            _position(
                account_id=account_id,
                symbol=symbol,
                direction=_sign(pos),
                quantity=total_opened,
                settlement=settlement,
                opened_at=opened_at,
                closed_at=None,
                realized=realized,
                fees=fees,
            )
        )
    return positions, None


def _position(
    *,
    account_id: int,
    symbol: str,
    direction: int,
    quantity: Decimal,
    settlement: int | None,
    opened_at: datetime | None,
    closed_at: datetime | None,
    realized: Decimal,
    fees: Decimal,
) -> FuturesPosition:
    assert settlement is not None and opened_at is not None
    return FuturesPosition(
        account_id=account_id,
        symbol=symbol,
        side="long" if direction > 0 else "short",
        quantity=quantity,
        settlement_instrument_id=settlement,
        opened_at=opened_at,
        closed_at=closed_at,
        realized=realized,
        fees=fees,
    )


def _sign(quantity: Decimal) -> int:
    return 1 if quantity > 0 else -1


@dataclass(frozen=True)
class SyncResult:
    """What one sync did: how many fills and payments were actually new —
    the dedupe key skipped the rest — and what the wholesale re-derivation
    of the source now states."""

    new_fills: int
    new_funding: int
    derivation: Derivation


def sync(
    engine: Engine,
    *,
    source: str,
    fills: Sequence[NormalizedFill] = (),
    funding: Sequence[NormalizedFunding] = (),
) -> SyncResult:
    """One source's sync, in one transaction: store what is new, rebuild the
    source's derived positions from its *entire* stored fill sequence
    (ADR-0009), and re-attribute every funding payment — attribution depends
    on the open intervals, which the rebuild may have moved."""
    with engine.begin() as connection:
        new_fills = repository.store_fills(connection, source, fills)
        new_funding = repository.store_funding(connection, source, funding)
        derivation = rebuild(connection, source)
    return SyncResult(new_fills=new_fills, new_funding=new_funding, derivation=derivation)


def rebuild(connection: Connection, source: str) -> Derivation:
    """Re-derive one source wholesale on the caller's transaction, and
    re-attribute every funding payment over the moved intervals."""
    derivation = derive(repository.fills_for_source(connection, source))
    repository.replace_derived(connection, source, derivation.positions, derivation.issues)
    _attribute(connection)
    return derivation


def record_manual_position(engine: Engine, position: FuturesPosition) -> int | Refusal:
    """The Admin's own position, in the one shared model — and funding
    re-attributed, because a new open interval may claim payments."""
    try:
        with engine.begin() as connection:
            position_id = repository.insert_manual(connection, position)
            _attribute(connection)
            return position_id
    except IntegrityError as refused:
        return repository.which_foundation_was_missing(refused)


def replace_manual_position(
    engine: Engine, position_id: int, position: FuturesPosition
) -> Refusal | None:
    """Revise a manual position wholesale. A derived position is refused by
    origin: it is the fills' statement, corrected only by correcting them."""
    try:
        with engine.begin() as connection:
            origin = repository.position_origin(connection, position_id)
            if origin is None:
                return Refusal.no_such_position
            if origin != "manual":
                return Refusal.not_manual
            repository.update_manual(connection, position_id, position)
            _attribute(connection)
            return None
    except IntegrityError as refused:
        return repository.which_foundation_was_missing(refused)


def delete_manual_position(engine: Engine, position_id: int) -> Refusal | None:
    with engine.begin() as connection:
        origin = repository.position_origin(connection, position_id)
        if origin is None:
            return Refusal.no_such_position
        if origin != "manual":
            return Refusal.not_manual
        repository.delete_position(connection, position_id)
        _attribute(connection)
        return None


def _attribute(connection: Connection) -> None:
    """Attribute every funding payment to the position open for its account
    and symbol at the payment instant — the half-open interval
    [opened_at, closed_at), so a payment at the closing instant belongs to
    whatever opened then, not to what just ended. A payment wearing a
    position side — enrichment some venues state in hedge mode — considers
    only that side. A payment with no open position, or with several — a
    hedge-mode long and short both open and the venue silent on which — is
    left unattributed and surfaced, never guessed or dropped."""
    positions, payments = repository.attribution_inputs(connection)
    intervals: dict[tuple[int, str], list] = {}
    for position in positions:
        intervals.setdefault((position.account_id, position.symbol), []).append(position)
    attributions: dict[int, int | None] = {}
    for payment in payments:
        candidates = [
            position
            for position in intervals.get((payment.account_id, payment.symbol), [])
            if position.opened_at <= payment.occurred_at
            and (position.closed_at is None or payment.occurred_at < position.closed_at)
            and (payment.position_side is None or position.side == payment.position_side)
        ]
        attributions[payment.id] = candidates[0].id if len(candidates) == 1 else None
    repository.set_attributions(connection, attributions)


def net_figure(position) -> Decimal:  # noqa: ANN001 — a position row or overview alike
    """The one net a position states (ticket 28): realised result less
    trading fees plus attributed funding — the figure a close emits into the
    Termingeschäfte pot (services/section20), summed from parts that stay
    separately stored and traceable."""
    return position.realized - position.fees + position.funding


@dataclass(frozen=True)
class PositionOverview:
    """One position as the Admin sees it: funding, trading fees and realised
    result separately, and the net figure they sum to — each traceable."""

    id: int
    origin: str
    source: str | None
    account_id: int
    symbol: str
    side: str
    quantity: Decimal
    settlement_instrument_id: int
    opened_at: datetime
    closed_at: datetime | None
    realized: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal


@dataclass(frozen=True)
class FundingOverview:
    """One payment no single position could claim — surfaced, never
    dropped."""

    id: int
    source: str
    account_id: int
    symbol: str
    amount: Decimal
    settlement_instrument_id: int
    occurred_at: datetime
    position_side: str | None


@dataclass(frozen=True)
class IssueOverview:
    id: int
    source: str
    account_id: int
    symbol: str
    position_side: str | None
    reason: str


@dataclass(frozen=True)
class FuturesOverview:
    positions: tuple[PositionOverview, ...]
    unattributable_funding: tuple[FundingOverview, ...]
    derivation_issues: tuple[IssueOverview, ...]


def overview(engine: Engine) -> FuturesOverview:
    """Everything the derivatives screen states, on one connection: the
    positions with their net figures, the funding nothing could claim, and
    the streams derivation refused to guess at."""
    with engine.connect() as connection:
        positions = repository.position_rows(connection)
        unattributable = repository.unattributable_rows(connection)
        issues = repository.issue_rows(connection)
    return FuturesOverview(
        positions=tuple(
            PositionOverview(
                id=row.id,
                origin=row.origin,
                source=row.source,
                account_id=row.account_id,
                symbol=row.symbol,
                side=row.side,
                quantity=row.quantity,
                settlement_instrument_id=row.settlement_instrument_id,
                opened_at=row.opened_at,
                closed_at=row.closed_at,
                realized=row.realized,
                fees=row.fees,
                funding=row.funding,
                net=net_figure(row),
            )
            for row in positions
        ),
        unattributable_funding=tuple(
            FundingOverview(
                id=row.id,
                source=row.source,
                account_id=row.account_id,
                symbol=row.symbol,
                amount=row.amount,
                settlement_instrument_id=row.settlement_instrument_id,
                occurred_at=row.occurred_at,
                position_side=row.position_side,
            )
            for row in unattributable
        ),
        derivation_issues=tuple(
            IssueOverview(
                id=row.id,
                source=row.source,
                account_id=row.account_id,
                symbol=row.symbol,
                position_side=row.position_side,
                reason=row.reason,
            )
            for row in issues
        ),
    )
