"""The column-mapping flow (ticket 33): the Admin's own declaration of a
file shape, judged complete before it saves or imports, and the mapped file
handed to the same machinery every shipped connector uses.

The provenance source is "mapping:<account_id>" — it stems from the flow,
never from which saved mapping read the file, so renaming, refining or
deleting a mapping cannot detach an Account from its own import history:
deduplication and the authoritative-source declaration hold to the Account's
one series of mapped files.
"""

from dataclasses import asdict, dataclass

from sqlalchemy import Engine, Row

from open_leprechaun.ports.column_mapping import ColumnMapping, MappingConnector, defects
from open_leprechaun.repositories import column_mappings as repository
from open_leprechaun.services import csv_imports
from open_leprechaun.services.csv_imports import CommitRefused, Committed, FileRefused, Preview


@dataclass(frozen=True)
class MappingIncomplete:
    """Why the mapping cannot be saved or imported yet: the port's own
    defect sentences, each naming a missing or contradictory declaration."""

    sentences: tuple[str, ...]


def save(engine: Engine, *, name: str, mapping: ColumnMapping) -> Row | MappingIncomplete:
    """Save the mapping under the name, replacing what the name held before —
    one name is one current declaration. Only a complete mapping saves; a
    half-built one answers its defects instead."""
    flaws = defects(mapping)
    if flaws:
        return MappingIncomplete(flaws)
    return repository.save(engine, name=name, definition=asdict(mapping))


def list_mappings(engine: Engine) -> list[Row]:
    return repository.list_mappings(engine)


def delete(engine: Engine, mapping_id: int) -> bool:
    return repository.delete(engine, mapping_id)


def preview(
    engine: Engine, *, account_id: int, content: str, mapping: ColumnMapping
) -> Preview | FileRefused:
    """What committing this file under this mapping would do, without writing
    anything — the framework's own preview, reached through the strict
    connector the mapping defines."""
    return csv_imports.preview_of(
        engine, MappingConnector(mapping), account_id=account_id, content=content
    )


def commit(
    engine: Engine, *, account_id: int, content: str, mapping: ColumnMapping, label: str
) -> Committed | CommitRefused | FileRefused:
    """The separate act the preview leads to: one reversible batch under the
    Account's mapping source."""
    return csv_imports.commit_of(
        engine, MappingConnector(mapping), account_id=account_id, content=content, label=label
    )
