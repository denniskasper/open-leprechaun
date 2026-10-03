"""Reconciliation (ticket 39, ADR-0008): what a venue says is held compared
against what the transactions account for — per Connection, per adapter kind,
per Instrument — with the difference surfaced rather than absorbed.

Nothing here writes to the ledger, and nothing could: a Normalized Position
is a snapshot, never history, so it can state that something is missing but
not what it cost or when it arrived. A gap is therefore reported and left
standing until the Admin closes it deliberately, by one of the two honest
resolutions — importing the history that explains it, or recording an
Opening Balance, which carries its own uncertainty marker (ticket 15).
Filling a gap from the snapshot would invent a cost basis.

Because it never writes, reconciliation ignores the authoritative-source
rule: a kind paired with an Account another source is authoritative for may
still compare against it — the free cross-check ADR-0008 promises.

The tracked side is the Tax Lot derivation's `held` (ADR-0019), the same
quantity the Holdings view states, so the two can never disagree. Each kind
acts and reports alone, like testing and syncing (ADR-0004).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.exchange import (
    Credentials,
    ExchangeAdapter,
    NormalizedPosition,
    StatesNormalizedPositions,
)
from open_leprechaun.repositories import connections as repository
from open_leprechaun.repositories import instruments as instruments_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import connections, lots
from open_leprechaun.services.exchange_sync import failure_sentence
from open_leprechaun.settings import Settings

Adapters = Mapping[str, Sequence[ExchangeAdapter]]

MATCHED = "matched"
GAP = "gap"
UNRESOLVED = "unresolved"

IMPORT_HISTORY = "import_history"
OPENING_BALANCE = "opening_balance"


@dataclass(frozen=True)
class Line:
    """One Instrument's comparison: `difference` is live less tracked, so a
    positive figure is quantity the venue holds that no transaction accounts
    for and a negative one quantity the ledger still tracks that the venue no
    longer shows. `resolutions` names the honest ways to close a gap — empty
    on a line that needs none.

    An unresolved line is a venue symbol no single Instrument answers to: it
    carries the live balance and the sentence saying why, and nothing
    tracked — which Instrument to compare against is exactly what is
    unknown."""

    instrument_id: int | None
    symbol: str
    name: str | None
    family: str | None
    live: Decimal
    tracked: Decimal | None
    difference: Decimal | None
    status: str
    resolutions: tuple[str, ...]
    detail: str | None


@dataclass(frozen=True)
class KindReconciliation:
    """One adapter kind's reconciliation against its paired Account. An
    error means nothing was compared; `as_of` is the latest instant the
    venue's snapshot states, None where it stated nothing."""

    adapter_kind: str
    error: str | None
    account_id: int | None
    as_of: datetime | None
    tolerance: Decimal
    lines: tuple[Line, ...]


def reconcile_connection(
    engine: Engine,
    settings: Settings,
    adapters: Adapters,
    connection_id: int,
    *,
    tolerance: Decimal | None = None,
) -> tuple[KindReconciliation, ...] | None:
    """Compare every kind that states positions against its paired Account.
    None when there is no such Connection; an empty answer when no kind of
    the venue states what is held. `tolerance` overrides the configured one
    for this run."""
    connection = repository.connection_row(engine, connection_id)
    if connection is None:
        return None
    sources = [
        adapter
        for adapter in adapters.get(connection.venue, ())
        if isinstance(adapter, StatesNormalizedPositions)
    ]
    if not sources:
        return ()
    credentials = connections.credentials_of(engine, settings, connection_id)
    if credentials is None:
        # The Connection vanished between the lookup and the decrypt.
        return None
    if tolerance is None:
        tolerance = settings.reconciliation_tolerance
    return tuple(
        _reconcile_kind(engine, connection, adapter, credentials, tolerance) for adapter in sources
    )


def _reconcile_kind(
    engine: Engine,
    connection: Row,
    adapter: ExchangeAdapter,
    credentials: Credentials,
    tolerance: Decimal,
) -> KindReconciliation:
    def refused(error: str, account_id: int | None = None) -> KindReconciliation:
        return KindReconciliation(
            adapter_kind=adapter.kind,
            error=error,
            account_id=account_id,
            as_of=None,
            tolerance=tolerance,
            lines=(),
        )

    account_id = repository.paired_account(engine, connection.id, adapter.kind)
    if account_id is None:
        return refused(
            f"The {adapter.kind} kind is not paired with an Account —"
            " choose which Account it reconciles against, then try again."
        )
    try:
        stated = tuple(adapter.normalized_positions(credentials))
    # Broad on purpose: one kind failing, however it failed, must never hide
    # another succeeding (ADR-0004).
    except Exception as failed:
        return refused(failure_sentence(failed), account_id)

    with lots.snapshot(engine) as snapshot:
        held = lots.derive_on(snapshot).held
        instruments = {row.id: row for row in lots_repository.instrument_rows(snapshot)}
    tracked = {
        instrument_id: quantity
        for (held_account_id, instrument_id), quantity in held.items()
        if held_account_id == account_id
    }
    live, unresolved = _by_instrument(engine, stated, tracked, tolerance)

    lines = []
    for instrument_id in sorted(live.keys() | tracked.keys()):
        live_quantity = live.get(instrument_id, Decimal(0))
        tracked_quantity = tracked.get(instrument_id, Decimal(0))
        if live_quantity == 0 and tracked_quantity == 0:
            # Held once, gone since, and the venue agrees — nothing to say.
            continue
        difference = live_quantity - tracked_quantity
        instrument = instruments[instrument_id]
        is_gap = abs(difference) > tolerance
        lines.append(
            Line(
                instrument_id=instrument_id,
                symbol=instrument.symbol,
                name=instrument.name,
                family=instrument.family,
                live=live_quantity,
                tracked=tracked_quantity,
                difference=difference,
                status=GAP if is_gap else MATCHED,
                resolutions=_resolutions(difference) if is_gap else (),
                detail=None,
            )
        )
    lines.sort(key=lambda line: (line.symbol, line.instrument_id))
    return KindReconciliation(
        adapter_kind=adapter.kind,
        error=None,
        account_id=account_id,
        as_of=max((position.as_of for position in stated), default=None),
        tolerance=tolerance,
        lines=(*lines, *unresolved),
    )


def _resolutions(difference: Decimal) -> tuple[str, ...]:
    """The honest ways to close a gap. Importing the missing history closes
    either direction. An Opening Balance only ever adds a position that
    predates the history, so it is offered where the venue holds more than
    the transactions account for — never to explain quantity away."""
    if difference > 0:
        return (IMPORT_HISTORY, OPENING_BALANCE)
    return (IMPORT_HISTORY,)


def _by_instrument(
    engine: Engine,
    stated: Sequence[NormalizedPosition],
    tracked: Mapping[int, Decimal],
    tolerance: Decimal,
) -> tuple[dict[int, Decimal], list[Line]]:
    """The venue's balances keyed by the Instrument each symbol names, summed
    where a venue states one asset in several places, and the symbols that
    name no single Instrument as unresolved lines.

    A symbol is a resolution hint, never an identity (ADR-0010): exactly one
    crypto or cash Instrument may wear it. Where several do, the one this
    Account already tracks answers — the transactions that put it there said
    which was meant; otherwise the line stays unresolved rather than guessed.
    """
    by_symbol: dict[str, Decimal] = {}
    for position in stated:
        by_symbol[position.symbol] = by_symbol.get(position.symbol, Decimal(0)) + position.quantity

    live: dict[int, Decimal] = {}
    unresolved: list[Line] = []
    for symbol, quantity in sorted(by_symbol.items()):
        wearing = instruments_repository.wearing_symbol(engine, symbol, families=("crypto", "cash"))
        shared = len(wearing) > 1
        if shared:
            wearing = [instrument_id for instrument_id in wearing if instrument_id in tracked]
        if len(wearing) == 1:
            live[wearing[0]] = live.get(wearing[0], Decimal(0)) + quantity
            continue
        if abs(quantity) <= tolerance:
            # Nothing tracked could answer, so the whole balance is the
            # difference — and one within tolerance is no gap here either.
            continue
        unresolved.append(
            Line(
                instrument_id=None,
                symbol=symbol,
                name=None,
                family=None,
                live=quantity,
                tracked=None,
                difference=None,
                status=UNRESOLVED,
                resolutions=(),
                detail=(
                    f"{symbol!r} names several Instruments and this Account tracks"
                    " none or several of them — the venue states only a symbol,"
                    " so the ledger cannot choose."
                    if shared
                    else f"No Instrument answers to {symbol!r} — create it, then reconcile again."
                ),
            )
        )
    return live, unresolved
