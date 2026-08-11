"""Every import shows exactly what it will create before it creates anything
(ticket 31). The preview and the commit run the same evaluation, so what the
preview promised is what the commit writes; nothing is written during preview,
and confirmation is a separate act that lands whole as one Import Batch,
reversible as a unit.

This module is the framework every connector and adapter (tickets 32, 33, 35)
hands its normalized rows to: connectors parse and normalize, this evaluation
alone decides what enters the ledger. Deduplication is keyed on source and
external identifier; exactly one source writes per Account, and a second may
reconcile but not write.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import imports, instruments
from open_leprechaun.repositories.imports import Refusal, WriteRow
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services.transactions import (
    TRANSACTION_TYPES,
    declaration_defect,
    structural_defect,
)

INSTRUMENT_KINDS = ("token", "native", "security", "cash")


@dataclass(frozen=True)
class InstrumentSpec:
    """How a row names an Instrument it cannot reference by id: the ledger's
    own identity attributes (ADR-0010) — chain and contract for a token,
    symbol for a native coin or cash, ISIN for a security. One that resolves
    to nothing is auto-created, arriving unacknowledged (ticket 14)."""

    kind: str
    symbol: str
    name: str
    chain: str | None = None
    contract_address: str | None = None
    security_type: str | None = None
    isin: str | None = None
    pegged_currency: str | None = None

    def defect(self) -> str | None:
        if self.kind not in INSTRUMENT_KINDS:
            return f"{self.kind!r} is not an Instrument kind."
        if self.kind == "token" and not (self.chain and self.contract_address):
            return "A token is identified by its chain and contract address."
        if self.kind == "native" and not self.chain:
            return "A native coin names its chain."
        if self.kind == "security" and not self.isin:
            return "A security is identified by its ISIN."
        return None

    def identity(self) -> tuple[str, ...]:
        """What makes two specs the same Instrument, per kind."""
        if self.kind == "token":
            return ("token", self.chain or "", (self.contract_address or "").lower())
        if self.kind == "security":
            return ("security", self.isin or "")
        return (self.kind, self.symbol)


@dataclass(frozen=True)
class ImportLeg:
    """One side of an imported event: the Instrument named by id or by
    identity, and exactly one of the two."""

    role: str
    quantity: Decimal
    instrument_id: int | None = None
    instrument: InstrumentSpec | None = None
    charged_against: int | None = None


@dataclass(frozen=True)
class ImportRow:
    external_id: str
    type: str
    occurred_at: datetime
    note: str | None = None
    legs: tuple[ImportLeg, ...] = ()


@dataclass(frozen=True)
class SkippedRow:
    external_id: str
    reason: str


@dataclass(frozen=True)
class CommitRefused:
    """Why a commit would not happen: which refusal, and the sentence that
    names it — composed here once, so no caller re-derives or re-queries it."""

    kind: Refusal
    sentence: str


@dataclass(frozen=True)
class Preview:
    """What a commit of these rows would do — computed without writing, so a
    cancelled import leaves no trace."""

    creatable: tuple[ImportRow, ...]
    duplicate_external_ids: tuple[str, ...]
    skipped: tuple[SkippedRow, ...]
    new_instruments: tuple[InstrumentSpec, ...]
    warnings: tuple[str, ...]
    # Why the commit would be refused — no such Account, or another source is
    # authoritative there. A preview is reconciliation and always allowed.
    refusal: CommitRefused | None


@dataclass(frozen=True)
class Committed:
    """batch_id is None when nothing was created — a pure re-import records
    no batch, because re-importing the same file changes nothing."""

    batch_id: int | None
    created: int
    duplicates: int
    skipped: int
    instruments_created: int


def evaluate(engine: Engine, *, source: str, account_id: int, rows: Sequence[ImportRow]) -> Preview:
    """Judge every row without writing anything: what would be created, what
    is already registered for this source, what is skipped and why, and which
    Instruments would have to be created first."""
    registered = imports.registered(engine, source)
    seen_in_file: set[str] = set()
    resolved: dict[tuple[str, ...], int | None] = {}
    known_ids: dict[int, bool] = {}
    creatable: list[ImportRow] = []
    duplicates: list[str] = []
    skipped: list[SkippedRow] = []
    new_instruments: dict[tuple[str, ...], InstrumentSpec] = {}

    for row in rows:
        if row.external_id in seen_in_file:
            repeated = "This external identifier appears earlier in the same file."
            skipped.append(SkippedRow(row.external_id, repeated))
            continue
        seen_in_file.add(row.external_id)
        if row.external_id in registered:
            duplicates.append(row.external_id)
            continue
        defect = _row_defect(engine, row, resolved, known_ids)
        if defect is not None:
            skipped.append(SkippedRow(row.external_id, defect))
            continue
        creatable.append(row)
        for leg in row.legs:
            if leg.instrument is not None and resolved[leg.instrument.identity()] is None:
                new_instruments.setdefault(leg.instrument.identity(), leg.instrument)

    warnings: list[str] = []
    if new_instruments:
        count = len(new_instruments)
        noun = "Instrument" if count == 1 else "Instruments"
        warnings.append(
            f"{count} {noun} will be created unacknowledged and wait in the inbox until classified."
        )

    refusal: CommitRefused | None = None
    account = imports.account_source(engine, account_id)
    if account is None:
        refusal = CommitRefused(Refusal.no_such_account, "No such Account.")
    elif account.kind == "broker" and account.withholding is None:
        # A Depot may not hold a position before its withholding behaviour is
        # set (ticket 43) — income there would be classified against an
        # unknown, so the preview names the repair and the commit refuses.
        sentence = (
            "The Depot's withholding behaviour is not set — record it on the"
            " broker Platform before importing into this Depot."
        )
        refusal = CommitRefused(Refusal.withholding_unset, sentence)
        warnings.append(sentence)
    elif account.authoritative_source not in (None, source):
        sentence = _not_authoritative(account.authoritative_source, source)
        refusal = CommitRefused(Refusal.not_authoritative, sentence)
        warnings.append(sentence)
    elif account.authoritative_source is None and creatable:
        warnings.append(
            f"Committing declares {source!r} the authoritative source for this Account;"
            " no other source may write after that."
        )

    return Preview(
        creatable=tuple(creatable),
        duplicate_external_ids=tuple(duplicates),
        skipped=tuple(skipped),
        new_instruments=tuple(new_instruments.values()),
        warnings=tuple(warnings),
        refusal=refusal,
    )


def commit(
    engine: Engine, *, source: str, label: str, account_id: int, rows: Sequence[ImportRow]
) -> Committed | CommitRefused:
    """The separate act the preview leads to: the same evaluation, then the
    batch, its Transactions and their registry rows written whole."""
    preview = evaluate(engine, source=source, account_id=account_id, rows=rows)
    if preview.refusal is not None:
        return preview.refusal
    if not preview.creatable:
        return Committed(
            batch_id=None,
            created=0,
            duplicates=len(preview.duplicate_external_ids),
            skipped=len(preview.skipped),
            instruments_created=0,
        )
    instruments_created = 0
    instrument_ids: dict[tuple[str, ...], int] = {}
    for spec in preview.new_instruments:
        instrument_id, was_created = _create_instrument(engine, spec)
        instrument_ids[spec.identity()] = instrument_id
        instruments_created += was_created
    outcome = imports.commit_batch(
        engine,
        source=source,
        label=label,
        account_id=account_id,
        rows=[_write_row(engine, row, account_id, instrument_ids) for row in preview.creatable],
    )
    if isinstance(outcome, Refusal):
        # The state changed between the evaluation and the write's row lock;
        # re-read so the sentence names whoever is authoritative now.
        return _refused(engine, outcome, account_id=account_id, source=source)
    return Committed(
        batch_id=outcome.batch_id,
        created=outcome.created,
        duplicates=len(preview.duplicate_external_ids) + outcome.raced,
        skipped=len(preview.skipped),
        instruments_created=instruments_created,
    )


def _not_authoritative(current: str, source: str) -> str:
    return (
        f"{current!r} is authoritative for this Account —"
        f" {source!r} may reconcile but may not write."
    )


def _refused(engine: Engine, refusal: Refusal, *, account_id: int, source: str) -> CommitRefused:
    if refusal is Refusal.no_such_account:
        return CommitRefused(refusal, "No such Account.")
    account = imports.account_source(engine, account_id)
    if account is None or account.authoritative_source is None:
        # The Account or its declaration vanished right after refusing; the
        # sentence can no longer name the winner, only the rule.
        return CommitRefused(
            refusal, f"Another source is authoritative for this Account — {source!r} may not write."
        )
    return CommitRefused(refusal, _not_authoritative(account.authoritative_source, source))


def _row_defect(
    engine: Engine,
    row: ImportRow,
    resolved: dict[tuple[str, ...], int | None],
    known_ids: dict[int, bool],
) -> str | None:
    """The sentence naming why this row cannot be created, or None when it
    can — the same judgements a hand-recorded event faces, plus the identity
    resolution only an import needs."""
    if row.type not in TRANSACTION_TYPES:
        return f"{row.type!r} is not in the transaction vocabulary."
    defect = structural_defect(row.type, row.legs) or declaration_defect(
        row.type, reconstructed=None, estimated_basis_eur=None
    )
    if defect is not None:
        return defect
    for leg in row.legs:
        if (leg.instrument_id is None) == (leg.instrument is None):
            return "A leg names its Instrument by id or by identity, and exactly one."
        if leg.quantity <= 0:
            return "A quantity is positive — direction is a leg's role."
        if leg.instrument_id is not None:
            if not _instrument_exists(engine, leg.instrument_id, known_ids):
                return "No such Instrument."
        else:
            spec_defect = leg.instrument.defect()
            if spec_defect is not None:
                return spec_defect
            _resolve(engine, leg.instrument, resolved)
    return None


def _instrument_exists(engine: Engine, instrument_id: int, known_ids: dict[int, bool]) -> bool:
    if instrument_id not in known_ids:
        known_ids[instrument_id] = instruments.get(engine, instrument_id) is not None
    return known_ids[instrument_id]


def _lookup(engine: Engine, spec: InstrumentSpec) -> int | None:
    return imports.find_instrument(
        engine,
        kind=spec.kind,
        symbol=spec.symbol,
        chain=spec.chain,
        contract_address=spec.contract_address,
        isin=spec.isin,
    )


def _resolve(
    engine: Engine, spec: InstrumentSpec, resolved: dict[tuple[str, ...], int | None]
) -> int | None:
    if spec.identity() not in resolved:
        resolved[spec.identity()] = _lookup(engine, spec)
    return resolved[spec.identity()]


def _create_instrument(engine: Engine, spec: InstrumentSpec) -> tuple[int, int]:
    """Create the Instrument the spec names, or resolve it when a racing
    import created it first — the unique indexes are the arbiter."""
    if spec.kind == "token":
        created = instruments.create_crypto_token(
            engine,
            symbol=spec.symbol,
            name=spec.name,
            chain=spec.chain,
            contract_address=spec.contract_address,
            pegged_currency=spec.pegged_currency,
        )
    elif spec.kind == "native":
        created = instruments.create_native_coin(
            engine, symbol=spec.symbol, name=spec.name, chain=spec.chain
        )
    elif spec.kind == "security":
        # An identifier the ledger did not know arrived by import: the row is
        # never dropped — the Instrument is minted flagged for review, typed
        # `unknown` where the source named no type (ticket 44).
        created = instruments.create_security(
            engine,
            symbol=spec.symbol,
            name=spec.name,
            type=spec.security_type or "unknown",
            isin=spec.isin,
            needs_review=True,
        )
    else:
        created = instruments.create_cash(engine, symbol=spec.symbol, name=spec.name)
    if created is not None:
        return created, 1
    resolved = _lookup(engine, spec)
    if resolved is None:
        raise LookupError(f"The Instrument {spec.symbol!r} could neither be created nor found.")
    return resolved, 0


def _write_row(
    engine: Engine,
    row: ImportRow,
    account_id: int,
    instrument_ids: dict[tuple[str, ...], int],
) -> WriteRow:
    legs = []
    for leg in row.legs:
        if leg.instrument_id is not None:
            instrument_id = leg.instrument_id
        elif leg.instrument.identity() in instrument_ids:
            instrument_id = instrument_ids[leg.instrument.identity()]
        else:
            instrument_id = _resolve(engine, leg.instrument, {})
        legs.append(
            Leg(
                account_id=account_id,
                instrument_id=instrument_id,
                role=leg.role,
                quantity=leg.quantity,
                charged_against=leg.charged_against,
            )
        )
    return WriteRow(
        external_id=row.external_id,
        type=row.type,
        occurred_at=row.occurred_at,
        note=row.note,
        legs=legs,
    )
