"""The CSV connector port (ticket 32, ADR-0008): the seam a venue's exported
file is confined behind.

A connector is the only place that knows one venue's export: the columns the
file carries, the timezone its timestamps are written in, and the units its
amounts use are all absorbed inside it — because an export in local time
silently produces wrong tax years, and one in sub-units silently produces
wrong quantities. What comes out are normalized rows in UTC and whole units,
naming assets by the venue's symbols alone: a connector never touches the
database, never converts to EUR and never computes tax, so it cannot know an
Instrument id or an Account. Resolving symbols against the ledger and handing
rows to the import framework is the csv_imports service's job.

A connector judges the whole file before rows come out: one that is not the
declared export, or a variant the connector cannot support, is refused with a
sentence rather than mis-parsed. What it can parse but deliberately declines
to import — an operation that moves no balance the ledger tracks — is skipped
with a warning naming it, never in silence.

A broker's exported statement comes through this same port (ticket 50): a
file is a file, whoever wrote it. What differs is what it can say — a
statement names a security by its ISIN and states income with what was
withheld from it — so such a connector answers the Normalized records the
broker port emits instead of symbol rows, and they land exactly as a Broker
Adapter's do. Which of the two a file yielded, never a connector's name,
decides how it lands.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from open_leprechaun.ports.broker import BrokerHarvest


@dataclass(frozen=True)
class NormalizedRow:
    """One ledger-bound event out of the file, already normalized: the
    timestamp converted to UTC from the connector's declared timezone, the
    quantity in whole units of the asset. `type` is the ledger's own
    transaction vocabulary; `fee_quantity` is a fee in the same asset,
    charged against the movement it enabled."""

    external_id: str
    occurred_at: datetime
    type: str
    symbol: str
    quantity: Decimal
    fee_quantity: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class ParsedFile:
    """Everything one file yielded: the rows to hand the import framework,
    and the sentences naming what the connector declined to import — so a
    skipped operation is a stated fact, never a silent hole.

    `statement` is what a broker's statement yielded instead of symbol rows:
    the broker port's own Normalized records and the period the statement
    covers, None for any other file."""

    rows: tuple[NormalizedRow, ...] = ()
    warnings: tuple[str, ...] = ()
    statement: BrokerHarvest | None = None


def cell(record: dict, column: str) -> str:
    """One cell of a csv.DictReader row, trimmed — a missing column and an
    empty one read the same, so every connector judges absence one way."""
    return (record.get(column) or "").strip()


class FileRejectedError(Exception):
    """The file is not the export this connector declared, or a variant it
    cannot support — refused whole with one sentence, because mis-parsing a
    wrong file writes wrong history."""


class CsvConnector(Protocol):
    """One venue's file import. `connector` is the registry key and the stem
    of the provenance source stamped on every imported row; `expects` names
    the export to produce, as UI copy; `timezone` is the IANA name the
    export's naive timestamps are read in — UTC only where the venue really
    writes UTC. `file_format` says what kind of file the export is, and so
    how its content reaches `parse`: a `csv` as the text it is, an `xlsx`
    workbook as its bytes in base64. `parse` answers the whole file or raises
    FileRejectedError."""

    @property
    def connector(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def expects(self) -> str: ...

    @property
    def timezone(self) -> str: ...

    @property
    def file_format(self) -> Literal["csv", "xlsx"]: ...

    def parse(self, content: str) -> ParsedFile: ...
