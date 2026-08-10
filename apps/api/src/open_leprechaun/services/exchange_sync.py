"""Testing and syncing a Connection through its venue's adapters (ticket 35,
ADR-0004, ADR-0008).

This is the only place adapter output meets the ledger, and it is where the
venue's symbols become the ledger's identities: each symbol is resolved
against the Instruments that exist — exactly one may answer, because a symbol
is a resolution hint, never an identity (ADR-0010) — and a symbol nothing or
several things answer to refuses the kind with a sentence instead of guessing.
Nothing here auto-creates an Instrument: an adapter cannot state a chain or a
contract, so minting identity from a bare symbol would collapse the very
distinction the Instrument model exists to keep.

Every kind acts alone and reports alone: its own Account pairing, its own
per-kind provenance string ("<venue>:<kind>") on everything it stores, its own
recorded result — one kind failing must never hide another succeeding
(ADR-0004). Ledger-bound records route through the import framework, which
already owns deduplication, the authoritative-source rule and batch
reversibility (ticket 31); fills and funding route through the futures
pipeline (ticket 28). Core code never learns a venue's name — the registry
hands over adapters, and everything after that is generic.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, Row

from open_leprechaun.ports.exchange import AdapterError, Credentials, ExchangeAdapter, Harvest
from open_leprechaun.repositories import connections as repository
from open_leprechaun.repositories import instruments as instruments_repository
from open_leprechaun.services import connections, futures, imports
from open_leprechaun.services.imports import CommitRefused, ImportLeg, ImportRow
from open_leprechaun.settings import Settings

Adapters = Mapping[str, Sequence[ExchangeAdapter]]


@dataclass(frozen=True)
class KindTest:
    """One adapter kind's test outcome: the venue's own sentence on success,
    the failure's sentence otherwise — never both."""

    adapter_kind: str
    detail: str | None
    error: str | None


def test_connection(
    engine: Engine, settings: Settings, adapters: Adapters, connection_id: int
) -> tuple[KindTest, ...] | None:
    """Prove the credentials open every kind the venue serves, recording each
    kind's outcome apart. None when there is no such Connection; an empty
    answer when the venue's adapters have not shipped yet."""
    connection = repository.connection_row(engine, connection_id)
    if connection is None:
        return None
    kinds = adapters.get(connection.venue, ())
    if not kinds:
        return ()
    credentials = connections.credentials_of(engine, settings, connection_id)
    if credentials is None:
        # The Connection vanished between the lookup and the decrypt.
        return None
    results = []
    for adapter in kinds:
        try:
            detail = adapter.test(credentials)
        # Broad on purpose: one kind failing, however it failed, must never
        # hide another succeeding (ADR-0004).
        except Exception as failed:
            error = _sentence(failed)
            connections.record_result(engine, connection_id, adapter.kind, error=error)
            results.append(KindTest(adapter_kind=adapter.kind, detail=None, error=error))
        else:
            connections.record_result(engine, connection_id, adapter.kind, error=None)
            results.append(KindTest(adapter_kind=adapter.kind, detail=detail, error=None))
    return tuple(results)


def _sentence(failed: Exception) -> str:
    """An AdapterError is the adapter's own recordable sentence, promised
    free of secret material. Anything else is a bug whose message promises
    nothing — it is withheld from what gets stored and shown (ADR-0003), and
    only the exception's type names the failure."""
    if isinstance(failed, AdapterError):
        return str(failed)
    return (
        f"The adapter failed unexpectedly ({type(failed).__name__}); the"
        " message is withheld in case it carries secret material."
    )


@dataclass(frozen=True)
class FuturesOutcome:
    """What landed in the futures pipeline: how many fills and payments were
    actually new — the dedupe key skipped the rest."""

    new_fills: int
    new_funding: int


@dataclass(frozen=True)
class ImportOutcome:
    """What the import framework did with the ledger-bound records. batch_id
    is None when nothing was new — a pure re-sync records no batch."""

    batch_id: int | None
    created: int
    duplicates: int
    skipped: int


@dataclass(frozen=True)
class KindSync:
    """One adapter kind's sync outcome. The outcomes stay present beside an
    error where part of the kind landed before the rest refused — what was
    stored is never unreported."""

    adapter_kind: str
    error: str | None
    futures: FuturesOutcome | None
    imported: ImportOutcome | None


def sync_connection(
    engine: Engine, settings: Settings, adapters: Adapters, connection_id: int
) -> tuple[KindSync, ...] | None:
    """Pull every kind the venue serves and land the records: fills and
    funding in the futures pipeline, ledger-bound rows through the import
    framework — each kind into its own paired Account under its own per-kind
    provenance string, each kind's outcome recorded apart (ADR-0004). None
    when there is no such Connection."""
    connection = repository.connection_row(engine, connection_id)
    if connection is None:
        return None
    kinds = adapters.get(connection.venue, ())
    if not kinds:
        return ()
    credentials = connections.credentials_of(engine, settings, connection_id)
    if credentials is None:
        # The Connection vanished between the lookup and the decrypt.
        return None
    results = []
    for adapter in kinds:
        result = _sync_kind(engine, connection, adapter, credentials)
        connections.record_result(engine, connection_id, adapter.kind, error=result.error)
        results.append(result)
    return tuple(results)


class _UnresolvableError(Exception):
    """A venue symbol the ledger cannot resolve to exactly one Instrument —
    the kind refuses with this sentence instead of guessing or minting."""


def _sync_kind(
    engine: Engine, connection: Row, adapter: ExchangeAdapter, credentials: Credentials
) -> KindSync:
    source = f"{connection.venue}:{adapter.kind}"
    account_id = repository.paired_account(engine, connection.id, adapter.kind)
    if account_id is None:
        return KindSync(
            adapter_kind=adapter.kind,
            error=f"The {adapter.kind} kind is not paired with an Account —"
            " choose where its records land, then sync again.",
            futures=None,
            imported=None,
        )
    try:
        harvest = adapter.pull(credentials)
        resolved, resolved_cash = _resolve_symbols(engine, harvest)
    except _UnresolvableError as unresolved:
        return KindSync(
            adapter_kind=adapter.kind, error=str(unresolved), futures=None, imported=None
        )
    # Broad on purpose: one kind failing, however it failed, must never hide
    # another succeeding (ADR-0004).
    except Exception as failed:
        return KindSync(
            adapter_kind=adapter.kind, error=_sentence(failed), futures=None, imported=None
        )

    futures_outcome = None
    if harvest.fills or harvest.funding:
        synced = futures.sync(
            engine,
            source=source,
            fills=tuple(
                futures.NormalizedFill(
                    external_id=fill.external_id,
                    account_id=account_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    price=fill.price,
                    size=fill.size,
                    fee=fill.fee,
                    settlement_instrument_id=resolved[fill.settlement_symbol],
                    occurred_at=fill.occurred_at,
                    position_side=fill.position_side,
                    reduce_only=fill.reduce_only,
                    realized=fill.realized,
                    inverse=fill.inverse,
                )
                for fill in harvest.fills
            ),
            funding=tuple(
                futures.NormalizedFunding(
                    external_id=payment.external_id,
                    account_id=account_id,
                    symbol=payment.symbol,
                    amount=payment.amount,
                    settlement_instrument_id=resolved[payment.settlement_symbol],
                    occurred_at=payment.occurred_at,
                    position_side=payment.position_side,
                )
                for payment in harvest.funding
            ),
        )
        futures_outcome = FuturesOutcome(new_fills=synced.new_fills, new_funding=synced.new_funding)

    imported_outcome = None
    error = None
    rows = _import_rows(harvest, resolved, resolved_cash)
    if rows:
        committed = imports.commit(
            engine,
            source=source,
            label=f"{connection.venue} {adapter.kind} sync",
            account_id=account_id,
            rows=rows,
        )
        if isinstance(committed, CommitRefused):
            error = committed.sentence
        else:
            imported_outcome = ImportOutcome(
                batch_id=committed.batch_id,
                created=committed.created,
                duplicates=committed.duplicates,
                skipped=committed.skipped,
            )
    return KindSync(
        adapter_kind=adapter.kind, error=error, futures=futures_outcome, imported=imported_outcome
    )


def _resolve_symbols(engine: Engine, harvest: Harvest) -> tuple[dict[str, int], dict[str, int]]:
    """Every symbol the harvest names, resolved to the one Instrument wearing
    it — crypto or cash for trades, transfers and settlements, the cash
    family alone for a cash movement's currency. A symbol nothing or several
    things answer to refuses the whole kind with a sentence: a symbol is a
    resolution hint, never an identity (ADR-0010)."""
    anywhere: set[str] = set()
    for trade in harvest.trades:
        anywhere.update((trade.base_symbol, trade.quote_symbol))
        if trade.fee_symbol is not None:
            anywhere.add(trade.fee_symbol)
    anywhere.update(transfer.symbol for transfer in harvest.transfers)
    anywhere.update(fill.settlement_symbol for fill in harvest.fills)
    anywhere.update(payment.settlement_symbol for payment in harvest.funding)
    cash = {movement.currency for movement in harvest.cash_movements}

    missing: list[str] = []
    several: list[str] = []
    resolved: dict[str, int] = {}
    resolved_cash: dict[str, int] = {}
    for symbol, families, into in [
        *((symbol, ("crypto", "cash"), resolved) for symbol in sorted(anywhere)),
        *((currency, ("cash",), resolved_cash) for currency in sorted(cash)),
    ]:
        ids = instruments_repository.wearing_symbol(engine, symbol, families=families)
        if len(ids) == 1:
            into[symbol] = ids[0]
        elif not ids:
            missing.append(symbol)
        else:
            several.append(symbol)
    if missing or several:
        sentences = []
        if missing:
            sentences.append(
                f"No Instrument answers to {_listed(missing)} — create it, then sync again."
            )
        if several:
            sentences.append(
                f"{_listed(several)} names several Instruments — the venue states only a"
                " symbol, so the ledger cannot choose."
            )
        raise _UnresolvableError(" ".join(sentences))
    return resolved, resolved_cash


def _listed(symbols: list[str]) -> str:
    return ", ".join(repr(symbol) for symbol in sorted(set(symbols)))


def _import_rows(
    harvest: Harvest, resolved: dict[str, int], resolved_cash: dict[str, int]
) -> list[ImportRow]:
    """The ledger-bound records as the import framework's own rows — trades
    with both sides present, each transfer side its own event where it
    happened, a cash movement a transfer of the cash Instrument."""
    rows: list[ImportRow] = []
    for trade in harvest.trades:
        received, gave = (
            ((trade.base_symbol, trade.base_quantity), (trade.quote_symbol, trade.quote_quantity))
            if trade.side == "buy"
            else (
                (trade.quote_symbol, trade.quote_quantity),
                (trade.base_symbol, trade.base_quantity),
            )
        )
        legs = [
            ImportLeg(role="in", quantity=received[1], instrument_id=resolved[received[0]]),
            ImportLeg(role="out", quantity=gave[1], instrument_id=resolved[gave[0]]),
        ]
        if trade.fee_symbol is not None and trade.fee_quantity:
            legs.append(
                ImportLeg(
                    role="fee",
                    quantity=trade.fee_quantity,
                    instrument_id=resolved[trade.fee_symbol],
                )
            )
        rows.append(
            ImportRow(
                external_id=trade.external_id,
                type="trade",
                occurred_at=trade.occurred_at,
                legs=tuple(legs),
            )
        )
    for transfer in harvest.transfers:
        role = "in" if transfer.direction == "in" else "out"
        legs = [
            ImportLeg(
                role=role, quantity=transfer.quantity, instrument_id=resolved[transfer.symbol]
            )
        ]
        if transfer.fee_quantity:
            legs.append(
                ImportLeg(
                    role="fee",
                    quantity=transfer.fee_quantity,
                    instrument_id=resolved[transfer.symbol],
                )
            )
        rows.append(
            ImportRow(
                external_id=transfer.external_id,
                type=f"transfer_{role}",
                occurred_at=transfer.occurred_at,
                legs=tuple(legs),
            )
        )
    for movement in harvest.cash_movements:
        role = "in" if movement.direction == "in" else "out"
        rows.append(
            ImportRow(
                external_id=movement.external_id,
                type=f"transfer_{role}",
                occurred_at=movement.occurred_at,
                legs=(
                    ImportLeg(
                        role=role,
                        quantity=movement.amount,
                        instrument_id=resolved_cash[movement.currency],
                    ),
                ),
            )
        )
    return rows
