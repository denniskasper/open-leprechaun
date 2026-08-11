"""Writes and reads over Import Batches and the deduplication registry.

The registry row is the durable fact of an import: unique on (source,
external_id), it outlives its Transaction as an overridden tombstone when the
Admin edits or deletes the row by hand, which is what keeps a re-import from
silently reverting the correction. The commit claims the Account's
authoritative source under a row lock, so exactly one ingestion mode writes
per Account and two racing commits cannot both declare themselves.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import Engine, Row, text

from open_leprechaun.repositories.transactions import Leg, insert_transaction


class Refusal(Enum):
    """Why a commit did not happen, in the Admin's terms rather than SQL's."""

    no_such_account = "no_such_account"
    not_authoritative = "not_authoritative"
    # The target is a Depot whose withholding behaviour nothing has set
    # (ticket 43) — no import may put a position where income could not be
    # classified.
    withholding_unset = "withholding_unset"


@dataclass(frozen=True)
class WriteRow:
    """One record cleared for writing: legs fully resolved to Instrument ids."""

    external_id: str
    type: str
    occurred_at: datetime
    note: str | None
    legs: list[Leg]


@dataclass(frozen=True)
class CommitOutcome:
    """batch_id is None when every row turned out to be a duplicate — nothing
    was written, so no batch exists to reverse."""

    batch_id: int | None
    created: int
    # Rows another commit registered between this one's preview and its write:
    # the unique registry constraint is the arbiter, so the race loses cleanly
    # and the row counts as the duplicate it is.
    raced: int


def registered(engine: Engine, source: str) -> set[str]:
    """Every external identifier the source has ever imported — tombstones of
    rows the Admin edited or deleted included, so those stay duplicates."""
    with engine.connect() as connection:
        return {
            row.external_id
            for row in connection.execute(
                text("SELECT external_id FROM imported_row WHERE source = :source"),
                {"source": source},
            )
        }


def account_source(engine: Engine, account_id: int) -> Row | None:
    """The Account's declared authoritative source, alongside what decides
    whether it may hold at all: its Platform's kind and its effective
    withholding behaviour — the Account's own override first, the Platform's
    word second (ticket 43). None when there is no such Account."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT account.authoritative_source, platform.kind,"
                " COALESCE(account.withholding_override, platform.withholding) AS withholding"
                " FROM account JOIN platform ON platform.id = account.platform_id"
                " WHERE account.id = :account_id"
            ),
            {"account_id": account_id},
        ).one_or_none()


def find_instrument(
    engine: Engine,
    *,
    kind: str,
    symbol: str,
    chain: str | None = None,
    contract_address: str | None = None,
    isin: str | None = None,
) -> int | None:
    """Resolve an identity the way the ledger keys it (ADR-0010): chain and
    contract for a token, symbol for a native coin or cash, ISIN — current or
    superseded, via the identifier history — for a security."""
    queries = {
        "token": (
            "SELECT id FROM instrument WHERE family = 'crypto' AND type = 'token'"
            " AND chain = :chain AND contract_address = lower(:contract_address)"
        ),
        "native": (
            "SELECT id FROM instrument WHERE family = 'crypto' AND type = 'native'"
            " AND symbol = :symbol"
        ),
        "security": (
            "SELECT instrument_id AS id FROM instrument_identifier"
            " WHERE kind = 'isin' AND value = :isin ORDER BY instrument_id LIMIT 1"
        ),
        "cash": "SELECT id FROM instrument WHERE family = 'cash' AND symbol = :symbol",
    }
    with engine.connect() as connection:
        return connection.execute(
            text(queries[kind]),
            {"symbol": symbol, "chain": chain, "contract_address": contract_address, "isin": isin},
        ).scalar_one_or_none()


def commit_batch(
    engine: Engine, *, source: str, label: str, account_id: int, rows: list[WriteRow]
) -> CommitOutcome | Refusal:
    """Write the batch, its Transactions and their registry rows in one
    database transaction — an import lands whole or not at all."""
    with engine.begin() as connection:
        account = connection.execute(
            text("SELECT authoritative_source FROM account WHERE id = :account_id FOR UPDATE"),
            {"account_id": account_id},
        ).one_or_none()
        if account is None:
            return Refusal.no_such_account
        if account.authoritative_source not in (None, source):
            return Refusal.not_authoritative
        if account.authoritative_source is None:
            connection.execute(
                text("UPDATE account SET authoritative_source = :source WHERE id = :account_id"),
                {"source": source, "account_id": account_id},
            )
        batch_id = connection.execute(
            text(
                "INSERT INTO import_batch (source, label, account_id)"
                " VALUES (:source, :label, :account_id) RETURNING id"
            ),
            {"source": source, "label": label, "account_id": account_id},
        ).scalar_one()
        created = raced = 0
        for row in rows:
            transaction_id = insert_transaction(
                connection,
                type=row.type,
                occurred_at=row.occurred_at,
                note=row.note,
                legs=row.legs,
            )
            claimed = connection.execute(
                text(
                    "INSERT INTO imported_row (batch_id, source, external_id, transaction_id)"
                    " VALUES (:batch_id, :source, :external_id, :transaction_id)"
                    " ON CONFLICT ON CONSTRAINT imported_row_once_per_source DO NOTHING"
                    " RETURNING id"
                ),
                {
                    "batch_id": batch_id,
                    "source": source,
                    "external_id": row.external_id,
                    "transaction_id": transaction_id,
                },
            ).scalar_one_or_none()
            if claimed is None:
                connection.execute(
                    text("DELETE FROM transaction WHERE id = :id"), {"id": transaction_id}
                )
                raced += 1
            else:
                created += 1
        if created == 0:
            # Everything raced to duplicate: nothing was written, so leave no
            # empty batch pretending something was.
            connection.execute(text("DELETE FROM import_batch WHERE id = :id"), {"id": batch_id})
            return CommitOutcome(batch_id=None, created=0, raced=raced)
        return CommitOutcome(batch_id=batch_id, created=created, raced=raced)


def list_batches(engine: Engine) -> list[Row]:
    """Newest first, each with how many registry rows it holds and how many
    of those the Admin has overridden."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT b.id, b.source, b.label, b.account_id, b.created_at,"
                    " count(r.id) AS rows,"
                    " count(r.id) FILTER (WHERE r.overridden) AS overridden"
                    " FROM import_batch b"
                    " LEFT JOIN imported_row r ON r.batch_id = b.id"
                    " GROUP BY b.id ORDER BY b.created_at DESC, b.id DESC"
                )
            ).all()
        )


def reverse_batch(engine: Engine, batch_id: int) -> bool:
    """Undo one import as a unit: its Transactions go, the batch goes, and
    the registry rows follow by cascade. Rows the Admin overrode are the
    Admin's now — their Transactions stand, and their tombstones detach from
    the batch so a re-import still counts them duplicates."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE imported_row SET batch_id = NULL WHERE batch_id = :batch_id AND overridden"
            ),
            {"batch_id": batch_id},
        )
        transaction_ids = [
            row.transaction_id
            for row in connection.execute(
                text(
                    "SELECT transaction_id FROM imported_row"
                    " WHERE batch_id = :batch_id AND transaction_id IS NOT NULL"
                ),
                {"batch_id": batch_id},
            )
        ]
        removed = connection.execute(
            text("DELETE FROM import_batch WHERE id = :batch_id"), {"batch_id": batch_id}
        )
        if removed.rowcount != 1:
            return False
        if transaction_ids:
            connection.execute(
                text("DELETE FROM transaction WHERE id = ANY(:ids)"), {"ids": transaction_ids}
            )
    return True


def list_provenance(engine: Engine) -> list[Row]:
    """Which batch and source each living imported Transaction came from, and
    whether the Admin has overridden it. Tombstones have no Transaction to
    annotate and are not listed."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT transaction_id, batch_id, source, overridden"
                    " FROM imported_row WHERE transaction_id IS NOT NULL"
                )
            ).all()
        )
