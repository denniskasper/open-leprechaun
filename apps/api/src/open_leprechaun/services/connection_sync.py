"""Testing and syncing a Connection through its venue's adapters (ticket 35,
ADR-0004, ADR-0008) — an exchange's and a broker's alike (ticket 48).

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
from typing import Literal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.broker import BrokerAdapter, BrokerHarvest, CoveredPeriod
from open_leprechaun.ports.exchange import AdapterError, Credentials, ExchangeAdapter, Harvest
from open_leprechaun.repositories import connections as repository
from open_leprechaun.repositories import instruments as instruments_repository
from open_leprechaun.services import broker_sync, connections, futures, imports
from open_leprechaun.services.import_prices import PriceSources, UnpricedRow
from open_leprechaun.services.imports import CommitRefused, ImportLeg, ImportRow
from open_leprechaun.services.price_reports import ProviderCondition
from open_leprechaun.settings import Settings

# Both account-authenticating ports reach the ledger here (ADR-0008): an
# exchange's kinds and a broker's hang off the same Connection, and what a
# kind pulled — not which port it implements — decides how it lands.
Adapters = Mapping[str, Sequence[ExchangeAdapter | BrokerAdapter]]


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
            error = failure_sentence(failed)
            connections.record_result(engine, connection_id, adapter.kind, error=error)
            results.append(KindTest(adapter_kind=adapter.kind, detail=None, error=error))
        else:
            connections.record_result(engine, connection_id, adapter.kind, error=None)
            results.append(KindTest(adapter_kind=adapter.kind, detail=detail, error=None))
    return tuple(results)


def failure_sentence(failed: Exception) -> str:
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
    # Created rows no provider could price at their own timestamp (ticket
    # 41) — named, never valued at zero — and what any failing provider's
    # failure was.
    unpriced: tuple[UnpricedRow, ...] = ()
    price_conditions: tuple[ProviderCondition, ...] = ()


@dataclass(frozen=True)
class MissingSymbol:
    """A symbol the venue stated that no Instrument answers to, and what would
    answer: a cash movement's currency resolves in the cash family alone, so
    only a currency does; any other symbol is answered by whatever wears it —
    None, where the kind is the Admin's to state."""

    symbol: str
    kind: Literal["cash"] | None


@dataclass(frozen=True)
class KindSync:
    """One adapter kind's sync outcome. The outcomes stay present beside an
    error where part of the kind landed before the rest refused — what was
    stored is never unreported."""

    adapter_kind: str
    error: str | None
    futures: FuturesOutcome | None
    imported: ImportOutcome | None
    # How far back the pull reached — the adapter's declared lookback
    # (ADR-0008), stated only once the pull succeeded, so "nothing found" is
    # never mistaken for "nothing exists". None where nothing was pulled.
    covered_days: int | None = None
    # The period a broker's pull reports having covered (ticket 48) — None
    # beside an error, and for a kind whose port reports none.
    covered_period: CoveredPeriod | None = None
    # What the venue stated that is no transaction — a split, a return of
    # capital — each a sentence naming what the Admin records by hand.
    passed_over: tuple[str, ...] = ()
    # The symbols the venue stated that no Instrument answers to — what the
    # Admin adds by hand before syncing again, each with the kind that would
    # answer; the error says the same in a sentence.
    missing: tuple[MissingSymbol, ...] = ()


def sync_connection(
    engine: Engine,
    settings: Settings,
    adapters: Adapters,
    connection_id: int,
    *,
    prices: PriceSources,
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
        result = _sync_kind(engine, connection, adapter, credentials, prices)
        connections.record_result(
            engine,
            connection_id,
            adapter.kind,
            error=result.error,
            # The days the pull reached over — already None beside an error,
            # so a failed kind claims no coverage (ticket 40).
            covered_lookback_days=result.covered_days,
            covered_from=None if result.covered_period is None else result.covered_period.start,
        )
        results.append(result)
    return tuple(results)


class _UnresolvableError(Exception):
    """A venue symbol the ledger cannot resolve to exactly one Instrument —
    the kind refuses with this sentence instead of guessing or minting."""

    def __init__(self, sentence: str, *, missing: tuple[MissingSymbol, ...]) -> None:
        super().__init__(sentence)
        self.missing = missing


def _sync_kind(
    engine: Engine,
    connection: Row,
    adapter: ExchangeAdapter | BrokerAdapter,
    credentials: Credentials,
    prices: PriceSources,
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
        # A broker names every Instrument by identity, so nothing of its
        # harvest waits on a symbol being resolved.
        resolved, resolved_cash = (
            ({}, {}) if isinstance(harvest, BrokerHarvest) else _resolve_symbols(engine, harvest)
        )
    except _UnresolvableError as unresolved:
        return KindSync(
            adapter_kind=adapter.kind,
            error=str(unresolved),
            futures=None,
            imported=None,
            missing=unresolved.missing,
        )
    # Broad on purpose: one kind failing, however it failed, must never hide
    # another succeeding (ADR-0004).
    except Exception as failed:
        return KindSync(
            adapter_kind=adapter.kind, error=failure_sentence(failed), futures=None, imported=None
        )

    if isinstance(harvest, BrokerHarvest):
        imported_outcome, error = _commit(
            engine, connection, adapter.kind, account_id, broker_sync.import_rows(harvest), prices
        )
        return KindSync(
            adapter_kind=adapter.kind,
            error=error,
            futures=None,
            imported=imported_outcome,
            covered_days=None if error else adapter.lookback_days,
            covered_period=None if error else harvest.covered,
            passed_over=broker_sync.passed_over(harvest),
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

    imported_outcome, error = _commit(
        engine,
        connection,
        adapter.kind,
        account_id,
        _import_rows(harvest, resolved, resolved_cash),
        prices,
    )
    return KindSync(
        adapter_kind=adapter.kind,
        error=error,
        futures=futures_outcome,
        imported=imported_outcome,
        # A refused commit means the account does not hold the period the
        # pull reached — an error and a coverage claim would contradict.
        covered_days=None if error else adapter.lookback_days,
    )


def _commit(
    engine: Engine,
    connection: Row,
    adapter_kind: str,
    account_id: int,
    rows: Sequence[ImportRow],
    prices: PriceSources,
) -> tuple[ImportOutcome | None, str | None]:
    """Land one kind's ledger-bound rows through the import framework under
    the kind's own provenance string. Answers what landed, or the sentence
    the commit was refused with — and neither where there was nothing to
    land."""
    if not rows:
        return None, None
    committed = imports.commit(
        engine,
        prices=prices,
        source=f"{connection.venue}:{adapter_kind}",
        label=f"{connection.venue} {adapter_kind} sync",
        account_id=account_id,
        rows=rows,
        # The kinds of one Connection are one credentialed link to one venue
        # account — one ingestion mode — so those paired with this Account
        # write into it together, each under its own provenance.
        alongside=tuple(
            f"{connection.venue}:{kind}"
            for kind in repository.kinds_paired_with(engine, connection.id, account_id)
        ),
    )
    if isinstance(committed, CommitRefused):
        return None, committed.sentence
    return (
        ImportOutcome(
            batch_id=committed.batch_id,
            created=committed.created,
            duplicates=committed.duplicates,
            skipped=committed.skipped,
            unpriced=committed.unpriced,
            price_conditions=committed.price_conditions,
        ),
        None,
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

    # What would answer to each missing symbol: a currency where a cash
    # movement names it — that settles a trade naming it too — else any kind.
    missing: dict[str, Literal["cash"] | None] = {}
    several: list[str] = []
    resolved: dict[str, int] = {}
    resolved_cash: dict[str, int] = {}
    for symbol, families, into, kind in [
        *((symbol, ("crypto", "cash"), resolved, None) for symbol in sorted(anywhere)),
        *((currency, ("cash",), resolved_cash, "cash") for currency in sorted(cash)),
    ]:
        ids = instruments_repository.wearing_symbol(engine, symbol, families=families)
        if len(ids) == 1:
            into[symbol] = ids[0]
        elif not ids:
            missing[symbol] = kind
        else:
            several.append(symbol)
    if missing or several:
        sentences = []
        if missing:
            sentences.append(
                f"No Instrument answers to {_listed(list(missing))} — create it, then sync again."
            )
        if several:
            sentences.append(
                f"{_listed(several)} names several Instruments — the venue states only a"
                " symbol, so the ledger cannot choose."
            )
        raise _UnresolvableError(
            " ".join(sentences),
            missing=tuple(
                MissingSymbol(symbol=symbol, kind=missing[symbol]) for symbol in sorted(missing)
            ),
        )
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
