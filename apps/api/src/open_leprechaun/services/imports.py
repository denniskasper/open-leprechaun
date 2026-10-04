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
from open_leprechaun.repositories.transactions import CapitalIncome, Leg, OriginalAmount
from open_leprechaun.services import import_prices
from open_leprechaun.services.import_prices import PriceSources, UnpricedRow
from open_leprechaun.services.price_reports import ProviderCondition
from open_leprechaun.services.transactions import (
    TRANSACTION_TYPES,
    declaration_defect,
    income_defect,
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
class ImportCapitalIncome:
    """What an imported dividend, distribution or interest declares beyond
    its legs (ADR-0022), as far as its source states it: the security that
    paid — named by identity, since the import may be the first the ledger
    hears of it — a Quellensteuer with its source country, and the German
    tax withheld at source in its three components."""

    paying_instrument: InstrumentSpec | None = None
    foreign_withholding: Decimal = Decimal(0)
    source_country: str | None = None
    kapitalertragsteuer: Decimal = Decimal(0)
    solidarity_surcharge: Decimal = Decimal(0)
    church_tax: Decimal = Decimal(0)


@dataclass(frozen=True)
class ImportRow:
    external_id: str
    type: str
    occurred_at: datetime
    note: str | None = None
    legs: tuple[ImportLeg, ...] = ()
    capital_income: ImportCapitalIncome | None = None
    # A trade's amount as it was priced, where it settled in another
    # currency (ADR-0025).
    original_amount: OriginalAmount | None = None

    def instrument_specs(self) -> tuple[InstrumentSpec, ...]:
        """Every Instrument this row names by identity — its legs' and its
        payer's alike, so either may be the one an import creates."""
        specs = [leg.instrument for leg in self.legs if leg.instrument is not None]
        if self.capital_income is not None and self.capital_income.paying_instrument is not None:
            specs.append(self.capital_income.paying_instrument)
        return tuple(specs)


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
    # Created rows no provider could price at their own timestamp (ticket
    # 41) — named, never valued at zero — and what any failing provider's
    # failure was.
    unpriced: tuple[UnpricedRow, ...] = ()
    price_conditions: tuple[ProviderCondition, ...] = ()


def evaluate(
    engine: Engine,
    *,
    source: str,
    account_id: int,
    rows: Sequence[ImportRow],
    alongside: Sequence[str] = (),
) -> Preview:
    """Judge every row without writing anything: what would be created, what
    is already registered for this source, what is skipped and why, and which
    Instruments would have to be created first.

    `alongside` names the sources that are the same ingestion mode as this
    one — the other kinds of one Connection writing into the same Account —
    so whichever of them declared itself authoritative does not lock the
    rest out."""
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
        for spec in row.instrument_specs():
            if resolved[spec.identity()] is None:
                new_instruments.setdefault(spec.identity(), spec)

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
    elif account.authoritative_source not in (None, source, *alongside):
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
    engine: Engine,
    *,
    prices: PriceSources,
    source: str,
    label: str,
    account_id: int,
    rows: Sequence[ImportRow],
    alongside: Sequence[str] = (),
) -> Committed | CommitRefused:
    """The separate act the preview leads to: the same evaluation, then the
    batch, its Transactions and their registry rows written whole. Once the
    batch has landed, every row that states no price of its own is given the
    price of its own day (ticket 41) — after, so that no provider's failure
    can cost the import."""
    preview = evaluate(engine, source=source, account_id=account_id, rows=rows, alongside=alongside)
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
        alongside=alongside,
    )
    if isinstance(outcome, Refusal):
        # The state changed between the evaluation and the write's row lock;
        # re-read so the sentence names whoever is authoritative now.
        return _refused(engine, outcome, account_id=account_id, source=source)
    resolution = (
        import_prices.resolve_batch(engine, prices, outcome.batch_id)
        if outcome.batch_id is not None
        else import_prices.Resolution()
    )
    return Committed(
        batch_id=outcome.batch_id,
        created=outcome.created,
        duplicates=len(preview.duplicate_external_ids) + outcome.raced,
        skipped=len(preview.skipped),
        instruments_created=instruments_created,
        unpriced=resolution.unpriced,
        price_conditions=resolution.conditions,
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
    if row.original_amount is not None and row.type != "trade":
        return "Only a trade states an amount as it was priced in another currency."
    declared = row.capital_income
    if declared is None:
        return None
    payer = declared.paying_instrument
    defect = income_defect(
        row.type,
        row.legs,
        CapitalIncome(
            # Only whether a payer is named is judged here; which Instrument
            # it resolves to is settled when the row is written.
            paying_instrument_id=None if payer is None else 0,
            foreign_withholding=declared.foreign_withholding,
            source_country=declared.source_country,
        ),
    )
    if defect is not None:
        return defect
    withheld = (
        declared.foreign_withholding,
        declared.kapitalertragsteuer,
        declared.solidarity_surcharge,
        declared.church_tax,
    )
    if any(amount < 0 for amount in withheld):
        return "A withheld amount is never negative."
    if payer is not None:
        if payer.defect() is not None:
            return payer.defect()
        _resolve(engine, payer, resolved)
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
    def instrument_id_of(spec: InstrumentSpec) -> int:
        if spec.identity() in instrument_ids:
            return instrument_ids[spec.identity()]
        return _resolve(engine, spec, {})

    legs = [
        Leg(
            account_id=account_id,
            instrument_id=leg.instrument_id
            if leg.instrument_id is not None
            else instrument_id_of(leg.instrument),
            role=leg.role,
            quantity=leg.quantity,
            charged_against=leg.charged_against,
        )
        for leg in row.legs
    ]
    capital_income = None
    if row.capital_income is not None:
        payer = row.capital_income.paying_instrument
        capital_income = CapitalIncome(
            paying_instrument_id=None if payer is None else instrument_id_of(payer),
            foreign_withholding=row.capital_income.foreign_withholding,
            source_country=row.capital_income.source_country,
            kapitalertragsteuer=row.capital_income.kapitalertragsteuer,
            solidarity_surcharge=row.capital_income.solidarity_surcharge,
            church_tax=row.capital_income.church_tax,
        )
    return WriteRow(
        external_id=row.external_id,
        type=row.type,
        occurred_at=row.occurred_at,
        note=row.note,
        legs=legs,
        capital_income=capital_income,
        original_amount=row.original_amount,
    )
