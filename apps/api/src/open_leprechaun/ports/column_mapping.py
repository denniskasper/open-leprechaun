"""The column-mapping CSV Connector (ticket 33): an unsupported venue does
not block the Admin. A ColumnMapping is the Admin's own declaration of one
file shape — which column carries which ledger field, the exact datetime
format and timezone, the delimiter and decimal convention — standing where a
shipped connector's venue knowledge would.

Nothing is guessed. An ambiguous date is read only under a declared format
and timezone; a type value the mapping does not name is a stated problem;
direction comes from the type, never from an amount's sign. The port reads a
file two ways: `interpret` is lenient — the mapping screen's live preview,
answering every row it can with the problems it cannot — and
`MappingConnector.parse` is strict, refusing a file the mapping cannot read
completely rather than mis-parsing it, exactly as any shipped connector
would.
"""

import csv
import hashlib
import io
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from open_leprechaun.ports.csv_connector import (
    FileRejectedError,
    NormalizedRow,
    ParsedFile,
    cell,
)

# The transaction types a mapped row may become: the single-role vocabulary,
# because one file row states one movement — a wallet's or broker's export
# neither trades nor converts in a single line. Kept as a literal so the port
# depends on no service; a test pins it to TRANSACTION_TYPES. Opening
# balances are deliberately absent — the declaration is the Admin's to own,
# never an import's.
MAPPED_TYPES = (
    "transfer_in",
    "transfer_out",
    "spend",
    "staking_reward",
    "lending_interest",
    "mining_reward",
    "airdrop",
    "windfall",
    "dividend",
    "distribution",
    "interest",
    "fee",
)

# A type value mapped to this is deliberately left out of the import — the
# Admin's explicit "these rows move nothing the ledger tracks", never silence.
LEAVE_OUT = ""


@dataclass(frozen=True)
class ColumnMapping:
    """One file shape as the Admin declared it. Every field is optional so a
    half-built mapping can still be interpreted for the live preview;
    `defects` names what a complete mapping still lacks, and the strict parse
    refuses while any defect stands."""

    # The column carrying the timestamp, its exact strptime format, and the
    # IANA timezone bare timestamps are read in. A format reading an offset
    # from each timestamp (%z) declares no timezone besides.
    occurred_at: str | None = None
    datetime_format: str | None = None
    timezone: str | None = None
    # The column carrying the moved amount. Direction comes from the type, so
    # a signed amount contributes its magnitude only.
    quantity: str | None = None
    # The asset's symbol: from a column, or one fixed symbol for the whole
    # file — exactly one of the two.
    symbol: str | None = None
    fixed_symbol: str | None = None
    # The transaction type: a column translated through `type_values`, or one
    # fixed type for the whole file — exactly one of the two. A translation
    # target is a MAPPED_TYPES entry, or LEAVE_OUT to drop those rows aloud.
    type: str | None = None
    fixed_type: str | None = None
    type_values: Mapping[str, str] = field(default_factory=dict)
    # The venue's own identifier column. Without one, an identifier is
    # derived from the row's content, so re-importing the same file still
    # changes nothing.
    external_id: str | None = None
    # A fee in the same asset, charged against the movement it enabled.
    fee_quantity: str | None = None
    note: str | None = None
    delimiter: str = ","
    # True where the file writes decimal commas ("1.234,56"); False where it
    # writes decimal points ("1,234.56"). The other mark is a group separator.
    decimal_comma: bool = False


@dataclass(frozen=True)
class InterpretedRow:
    """One file row read under the mapping: the ledger-bound values where the
    cells could be read, a problem sentence for each cell that could not, and
    the reason where the import would deliberately leave the row out."""

    number: int
    external_id: str | None = None
    occurred_at: datetime | None = None
    type: str | None = None
    symbol: str | None = None
    quantity: Decimal | None = None
    fee_quantity: Decimal | None = None
    note: str | None = None
    left_out: str | None = None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Interpretation:
    """The live preview's whole answer: the columns the file carries (the
    mapping screen builds its pickers from these), the first rows as they
    would be interpreted, and every defect still standing — in the mapping
    itself, or between the mapping and this file's header."""

    columns: tuple[str, ...]
    rows: tuple[InterpretedRow, ...]
    row_count: int
    defects: tuple[str, ...]
    # Every distinct value the mapped type column carries, over the whole
    # file — the mapping screen builds its translation rows from these, so a
    # value first appearing deep in the file still gets its row.
    type_values_seen: tuple[str, ...] = ()


def defects(mapping: ColumnMapping) -> tuple[str, ...]:
    """Every sentence naming why this mapping is not yet a complete
    declaration. The import proceeds only on an empty answer."""
    found: list[str] = []
    if not mapping.occurred_at:
        found.append("No column is assigned to the timestamp.")
    if not mapping.datetime_format:
        found.append("The datetime format is not declared — an ambiguous date is never guessed.")
    elif "%" not in mapping.datetime_format:
        found.append(f"{mapping.datetime_format!r} is not a datetime format.")
    if mapping.datetime_format and "%z" in mapping.datetime_format:
        if mapping.timezone:
            found.append(
                "The format reads a UTC offset from each timestamp, so a timezone is not"
                " declared besides."
            )
    elif not mapping.timezone:
        found.append("The timezone is not declared — a bare timestamp is never guessed.")
    if mapping.timezone:
        try:
            ZoneInfo(mapping.timezone)
        except ZoneInfoNotFoundError, ValueError:
            found.append(f"{mapping.timezone!r} is not an IANA timezone name.")
    if not mapping.quantity:
        found.append("No column is assigned to the quantity.")
    found.extend(_one_of(mapping.symbol, mapping.fixed_symbol, "symbol"))
    found.extend(_one_of(mapping.type, mapping.fixed_type, "type"))
    outside = sorted(
        {
            target
            for target in (mapping.fixed_type, *mapping.type_values.values())
            if target is not None and target != LEAVE_OUT and target not in MAPPED_TYPES
        }
    )
    if outside:
        listed = ", ".join(repr(target) for target in outside)
        found.append(f"{listed} is not an importable transaction type.")
    if len(mapping.delimiter) != 1:
        found.append("The delimiter is a single character.")
    return tuple(found)


def interpret(content: str, mapping: ColumnMapping, limit: int | None = 20) -> Interpretation:
    """Every row the file carries, read leniently under the mapping — the
    mapping screen's live preview. What a cell cannot yield is a problem
    sentence on its row; what the mapping itself still lacks is a defect."""
    found = list(defects(mapping))
    if len(mapping.delimiter) != 1:
        # Nothing is read under a delimiter the Admin never declared cleanly
        # — and csv itself would refuse it with a crash, not a sentence.
        return Interpretation(columns=(), rows=(), row_count=0, defects=tuple(found))
    reader = csv.DictReader(io.StringIO(content.removeprefix("﻿")), delimiter=mapping.delimiter)
    columns = tuple(reader.fieldnames or ())
    if not columns:
        found.append("The file has no header row.")
    for column in _assigned_columns(mapping):
        if columns and column not in columns:
            found.append(f"The file has no column {column!r}.")
    rows: list[InterpretedRow] = []
    count = 0
    derived_ids: Counter[str] = Counter()
    type_values_seen: set[str] = set()
    for record in reader:
        if not any((value or "").strip() for value in record.values() if value is not None):
            continue
        count += 1
        if mapping.type and mapping.type in columns and _cell(record, mapping.type):
            type_values_seen.add(_cell(record, mapping.type))
        if limit is None or len(rows) < limit:
            rows.append(_interpret_row(record, mapping, count, columns, derived_ids))
    return Interpretation(
        columns=columns,
        rows=tuple(rows),
        row_count=count,
        defects=tuple(found),
        type_values_seen=tuple(sorted(type_values_seen)),
    )


@dataclass(frozen=True)
class MappingConnector:
    """The strict reading of a file under a complete mapping, wearing the CSV
    Connector port so a mapped file flows through the same preview, batch and
    reversal machinery as any shipped connector's. The provenance source
    stems from "mapping" alone — whichever saved mapping read the file, the
    Account's rows belong to one series."""

    mapping: ColumnMapping
    connector: str = "mapping"
    name: str = "Column mapping"
    expects: str = "Any exported CSV, read under the Admin's own column mapping."

    @property
    def timezone(self) -> str:
        return self.mapping.timezone or "UTC"

    def parse(self, content: str) -> ParsedFile:
        interpretation = interpret(content, self.mapping, limit=None)
        if interpretation.defects:
            raise FileRejectedError(" ".join(interpretation.defects))
        rows: list[NormalizedRow] = []
        left_out: Counter[str] = Counter()
        for row in interpretation.rows:
            if row.problems:
                raise FileRejectedError(f"Row {row.number}: {row.problems[0]}")
            if row.left_out is not None:
                left_out[row.left_out] += 1
                continue
            rows.append(
                NormalizedRow(
                    external_id=row.external_id,
                    occurred_at=row.occurred_at,
                    type=row.type,
                    symbol=row.symbol,
                    quantity=row.quantity,
                    fee_quantity=row.fee_quantity,
                    note=row.note,
                )
            )
        return ParsedFile(rows=tuple(rows), warnings=_warnings(left_out))


def _one_of(column: str | None, fixed: str | None, name: str) -> tuple[str, ...]:
    if column and fixed:
        return (f"The {name} comes from a column or is fixed for the whole file — not both.",)
    if not column and not fixed:
        return (f"The {name} comes from a column or is fixed for the whole file; assign one.",)
    return ()


def _assigned_columns(mapping: ColumnMapping) -> tuple[str, ...]:
    assigned = (
        mapping.occurred_at,
        mapping.quantity,
        mapping.symbol,
        mapping.type,
        mapping.external_id,
        mapping.fee_quantity,
        mapping.note,
    )
    return tuple(column for column in assigned if column)


def _interpret_row(
    record: dict,
    mapping: ColumnMapping,
    number: int,
    columns: tuple[str, ...],
    derived_ids: Counter[str],
) -> InterpretedRow:
    problems: list[str] = []
    left_out: str | None = None

    occurred_at = _occurred_at(record, mapping, columns, problems)
    quantity = _cell_decimal(record, mapping.quantity, mapping, columns, "quantity", problems)
    if quantity is not None and quantity == 0:
        left_out = "moved no amount"
    fee_quantity = _cell_decimal(record, mapping.fee_quantity, mapping, columns, "fee", problems)
    if fee_quantity == 0:
        fee_quantity = None

    symbol = mapping.fixed_symbol or None
    if mapping.symbol and mapping.symbol in columns:
        symbol = _required_cell(record, mapping.symbol, "symbol", problems)

    type, type_left_out = _type(record, mapping, columns, problems)
    left_out = type_left_out or left_out

    note = _cell(record, mapping.note) or None
    external_id = _external_id(record, mapping, columns, problems, derived_ids)

    return InterpretedRow(
        number=number,
        external_id=external_id,
        occurred_at=occurred_at,
        type=type,
        symbol=symbol,
        quantity=quantity,
        fee_quantity=fee_quantity,
        note=note,
        left_out=left_out,
        problems=tuple(problems),
    )


def _cell(record: dict, column: str | None) -> str:
    """The port's shared `cell`, for a column the mapping may not assign."""
    return cell(record, column) if column else ""


def _required_cell(record: dict, column: str, name: str, problems: list[str]) -> str | None:
    raw = _cell(record, column)
    if not raw:
        problems.append(f"The {name} column {column!r} is empty on this row.")
        return None
    return raw


def _occurred_at(
    record: dict, mapping: ColumnMapping, columns: tuple[str, ...], problems: list[str]
) -> datetime | None:
    if not (
        mapping.occurred_at
        and mapping.occurred_at in columns
        and mapping.datetime_format
        and "%" in mapping.datetime_format
    ):
        return None
    raw = _required_cell(record, mapping.occurred_at, "timestamp", problems)
    if raw is None:
        return None
    try:
        parsed = datetime.strptime(raw, mapping.datetime_format)
    except ValueError:
        problems.append(
            f"The timestamp {raw!r} does not match the format {mapping.datetime_format!r}."
        )
        return None
    if parsed.tzinfo is None:
        if not mapping.timezone:
            return None
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(mapping.timezone))
        except ZoneInfoNotFoundError, ValueError:
            return None
    return parsed.astimezone(UTC)


def _cell_decimal(
    record: dict,
    column: str | None,
    mapping: ColumnMapping,
    columns: tuple[str, ...],
    name: str,
    problems: list[str],
) -> Decimal | None:
    if not column or column not in columns:
        return None
    raw = _cell(record, column)
    if not raw:
        if name == "quantity":
            problems.append(f"The quantity column {column!r} is empty on this row.")
        return None
    # Group separators go, the declared decimal mark becomes the point;
    # direction is the type's business, so the sign contributes nothing.
    cleaned = raw.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    if mapping.decimal_comma:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return abs(Decimal(cleaned))
    except InvalidOperation:
        problems.append(f"The {name} {raw!r} is not a number the mapping can read.")
        return None


def _type(
    record: dict, mapping: ColumnMapping, columns: tuple[str, ...], problems: list[str]
) -> tuple[str | None, str | None]:
    """The row's transaction type and, where the mapping deliberately drops
    this row, the phrase saying so."""
    if mapping.fixed_type:
        return (mapping.fixed_type if mapping.fixed_type in MAPPED_TYPES else None), None
    if not (mapping.type and mapping.type in columns):
        return None, None
    raw = _required_cell(record, mapping.type, "type", problems)
    if raw is None:
        return None, None
    if raw not in mapping.type_values:
        problems.append(f"The type value {raw!r} is not mapped — map it, or leave it out.")
        return None, None
    target = mapping.type_values[raw]
    if target == LEAVE_OUT:
        return None, f"{raw!r} is mapped to be left out"
    return (target if target in MAPPED_TYPES else None), None


def _external_id(
    record: dict,
    mapping: ColumnMapping,
    columns: tuple[str, ...],
    problems: list[str],
    derived_ids: Counter[str],
) -> str | None:
    if mapping.external_id:
        if mapping.external_id not in columns:
            return None
        return _required_cell(record, mapping.external_id, "identifier", problems)
    # No identifier column: derive one from the row's own content, an
    # occurrence counter keeping two genuinely identical rows distinct — so a
    # re-import of the same file still changes nothing.
    material = "|".join(
        (
            _cell(record, mapping.occurred_at),
            mapping.fixed_type or _cell(record, mapping.type),
            mapping.fixed_symbol or _cell(record, mapping.symbol),
            _cell(record, mapping.quantity),
            _cell(record, mapping.fee_quantity),
            _cell(record, mapping.note),
        )
    )
    occurrence = derived_ids[material]
    derived_ids[material] += 1
    return hashlib.sha256(f"{material}|{occurrence}".encode()).hexdigest()


def _warnings(left_out: Counter[str]) -> tuple[str, ...]:
    if not left_out:
        return ()
    total = sum(left_out.values())
    noun = "row" if total == 1 else "rows"
    counted = ", ".join(f"{reason} x{count}" for reason, count in sorted(left_out.items()))
    return (f"{total} {noun} left out: {counted}.",)
