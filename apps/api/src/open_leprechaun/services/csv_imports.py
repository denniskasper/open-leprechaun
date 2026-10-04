"""One exported file through the import framework (ticket 32, ADR-0008): the
connector parses and normalizes, this service resolves the venue's symbols
against the ledger, and the framework's own evaluation (services/imports)
alone decides what enters — preview first, commit as a separate act.

Symbols resolve the way the exchange sync resolves them: exactly one
Instrument may answer, because a symbol is a resolution hint, never an
identity (ADR-0010) — a file naming something the ledger does not hold is
refused whole with a sentence instead of guessing or minting.

The provenance source is the connector's name scoped by the Account the file
lands in ("bitbox:3"), so deduplication holds a file to its Account: two
Accounts fed by the same connector never swallow each other's rows — a
transfer between two of the Admin's own wallets appears in both exports under
one transaction id, and both sides are facts.

A broker's statement (ticket 50) yields the broker port's Normalized records
instead of symbol rows, and they become import rows by the same translation a
Broker Adapter's harvest goes through (services/broker_sync) — every
Instrument named by identity, so an unknown security arrives flagged for
review instead of refusing the file. What a file yielded decides the path,
never the connector's name.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from open_leprechaun.ports.broker import (
    BrokerHarvest,
    CoveredPeriod,
    NormalizedDividend,
    NormalizedSecurityTrade,
)
from open_leprechaun.ports.csv_connector import CsvConnector, FileRejectedError, NormalizedRow
from open_leprechaun.repositories import instruments as instruments_repository
from open_leprechaun.services import broker_sync, imports
from open_leprechaun.services.import_prices import PriceSources
from open_leprechaun.services.imports import CommitRefused, Committed, ImportLeg, ImportRow, Preview
from open_leprechaun.services.transactions import TRANSACTION_TYPES

Connectors = Mapping[str, CsvConnector]


@dataclass(frozen=True)
class FileRefused:
    """Why no rows were even evaluated: the connector refused the file, or a
    symbol resolved to nothing or to several Instruments — one sentence,
    safe to show."""

    sentence: str


def source_of(connector: str, account_id: int) -> str:
    """The provenance stamped on everything this connector imports into this
    Account — one half of the deduplication key, and what the Account's
    authoritative-source declaration names."""
    return f"{connector}:{account_id}"


def preview(
    engine: Engine, connectors: Connectors, *, connector: str, account_id: int, content: str
) -> Preview | FileRefused | None:
    """What committing this file would do, without writing anything. None
    when no connector wears the name."""
    chosen = connectors.get(connector)
    if chosen is None:
        return None
    return preview_of(engine, chosen, account_id=account_id, content=content)


def preview_of(
    engine: Engine, connector: CsvConnector, *, account_id: int, content: str
) -> Preview | FileRefused:
    """The preview under one connector object — the seam the column-mapping
    flow (ticket 33) shares, its connector built per request rather than
    registered. The connector's own warnings lead the framework's, because
    what the file could not yield is judged first."""
    rows = _rows(engine, connector, content)
    if isinstance(rows, FileRefused):
        return rows
    parsed_warnings, import_rows = rows
    evaluated = imports.evaluate(
        engine,
        source=source_of(connector.connector, account_id),
        account_id=account_id,
        rows=import_rows,
    )
    return replace(evaluated, warnings=parsed_warnings + evaluated.warnings)


def commit(
    engine: Engine,
    connectors: Connectors,
    *,
    prices: PriceSources,
    connector: str,
    account_id: int,
    content: str,
    label: str,
) -> Committed | CommitRefused | FileRefused | None:
    """The separate act the preview leads to — the same parse and resolution,
    the framework's own commit, one reversible batch."""
    chosen = connectors.get(connector)
    if chosen is None:
        return None
    return commit_of(
        engine, chosen, prices=prices, account_id=account_id, content=content, label=label
    )


def commit_of(
    engine: Engine,
    connector: CsvConnector,
    *,
    prices: PriceSources,
    account_id: int,
    content: str,
    label: str,
) -> Committed | CommitRefused | FileRefused:
    rows = _rows(engine, connector, content)
    if isinstance(rows, FileRefused):
        return rows
    _, import_rows = rows
    return imports.commit(
        engine,
        prices=prices,
        source=source_of(connector.connector, account_id),
        label=label,
        account_id=account_id,
        rows=import_rows,
    )


def _rows(
    engine: Engine, connector: CsvConnector, content: str
) -> tuple[tuple[str, ...], list[ImportRow]] | FileRefused:
    try:
        parsed = connector.parse(content)
    except FileRejectedError as rejected:
        return FileRefused(str(rejected))
    resolved = _resolve_symbols(engine, {row.symbol for row in parsed.rows})
    if isinstance(resolved, FileRefused):
        return resolved
    warnings = parsed.warnings
    import_rows = [_import_row(row, resolved) for row in parsed.rows]
    if parsed.statement is not None:
        # A broker's statement: its records land as a Broker Adapter's do,
        # and what it states that is no transaction is named, never dropped.
        statement, unanswered = _resolve_tickers(engine, parsed.statement)
        import_rows.extend(broker_sync.import_rows(statement))
        warnings = (
            _covered_words(statement.covered, connector.timezone),
            *warnings,
            *unanswered,
            *broker_sync.passed_over(statement),
        )
    return warnings, import_rows


def _resolve_tickers(engine: Engine, statement: BrokerHarvest) -> tuple[BrokerHarvest, list[str]]:
    """A statement names a security by its ISIN where it states one. Where
    it names only a ticker, that is a resolution hint (ADR-0010): exactly one
    security in the ledger may answer to it — wearing it as its symbol or as a
    ticker alias — and the record then lands under that security's ISIN. A
    ticker nothing or several things answer to mints nothing and refuses
    nothing: its rows are left out with a sentence, and the rest lands."""
    answers: dict[str, set[str]] = {}
    left_out: Counter[str] = Counter()

    def named[Record: NormalizedSecurityTrade | NormalizedDividend](
        records: tuple[Record, ...],
    ) -> tuple[Record, ...]:
        kept = []
        for record in records:
            security = record.security
            if security is None or security.isin is not None:
                kept.append(record)
                continue
            if security.symbol not in answers:
                answers[security.symbol] = {
                    row.isin
                    for row in instruments_repository.answering_to_ticker(engine, security.symbol)
                }
            if len(answers[security.symbol]) == 1:
                (isin,) = answers[security.symbol]
                kept.append(replace(record, security=replace(security, isin=isin)))
            else:
                left_out[security.symbol] += 1
        return tuple(kept)

    resolved = replace(
        statement, trades=named(statement.trades), dividends=named(statement.dividends)
    )
    # A hint that was answered is said too: the Admin sees which security
    # the ledger took a ticker to mean before anything lands under it.
    sentences = [
        f"The statement names {ticker!r} by its ticker alone; its rows land under the one"
        f" security in the ledger answering to it, {next(iter(isins))}."
        for ticker, isins in sorted(answers.items())
        if len(isins) == 1
    ]
    for ticker, count in sorted(left_out.items()):
        rows = "1 row was" if count == 1 else f"{count} rows were"
        sentences.append(
            f"The statement names {ticker!r} by its ticker alone, and no security in the"
            f" ledger answers to it — {rows} left out. Create the security with that symbol"
            " or ticker, then import again."
            if not answers[ticker]
            else f"The statement names {ticker!r} by its ticker alone, and several securities"
            f" in the ledger answer to it — {rows} left out, because the ledger cannot choose."
        )
    return resolved, sentences


def _covered_words(covered: CoveredPeriod, timezone: str) -> str:
    """How far the statement reaches, on its own declared clock — the dates
    the broker printed. A broker served by import is current only this far."""
    zone = ZoneInfo(timezone)
    end = covered.end.astimezone(zone).date().isoformat()
    if covered.start is None:
        return f"The statement covers everything up to {end}."
    return f"The statement covers {covered.start.astimezone(zone).date().isoformat()} to {end}."


def _resolve_symbols(engine: Engine, symbols: set[str]) -> dict[str, int] | FileRefused:
    """Every symbol the file names, resolved to the one Instrument wearing
    it — refused whole when nothing or several things answer, with the same
    sentences the exchange sync refuses with."""
    missing: list[str] = []
    several: list[str] = []
    resolved: dict[str, int] = {}
    for symbol in sorted(symbols):
        ids = instruments_repository.wearing_symbol(engine, symbol, families=("crypto", "cash"))
        if len(ids) == 1:
            resolved[symbol] = ids[0]
        elif not ids:
            missing.append(symbol)
        else:
            several.append(symbol)
    if missing or several:
        sentences = []
        if missing:
            sentences.append(
                f"No Instrument answers to {_listed(missing)} — create it, then import again."
            )
        if several:
            sentences.append(
                f"{_listed(several)} names several Instruments — the file states only a"
                " symbol, so the ledger cannot choose."
            )
        return FileRefused(" ".join(sentences))
    return resolved


def _listed(symbols: list[str]) -> str:
    return ", ".join(repr(symbol) for symbol in sorted(set(symbols)))


def _import_row(row: NormalizedRow, resolved: dict[str, int]) -> ImportRow:
    """One normalized row as the framework's own row. The moved quantity
    takes the role its type requires; a fee rides as its own leg charged
    against the movement it enabled. A type outside the vocabulary builds no
    legs — the evaluation refuses it with its own sentence."""
    instrument_id = resolved[row.symbol]
    legs: tuple[ImportLeg, ...] = ()
    rules = TRANSACTION_TYPES.get(row.type)
    # Only single-role types fit this row shape (a wallet neither trades nor
    # converts); anything else keeps no legs and the evaluation refuses it.
    if rules is not None and len(rules.requires) == 1:
        (role,) = rules.requires
        legs = (ImportLeg(role=role, quantity=row.quantity, instrument_id=instrument_id),)
        if row.fee_quantity:
            legs += (
                ImportLeg(
                    role="fee",
                    quantity=row.fee_quantity,
                    instrument_id=instrument_id,
                    # By position: the movement leg is the first and only
                    # other leg this row shape builds.
                    charged_against=0,
                ),
            )
    return ImportRow(
        external_id=row.external_id,
        type=row.type,
        occurred_at=row.occurred_at,
        note=row.note,
        legs=legs,
    )
