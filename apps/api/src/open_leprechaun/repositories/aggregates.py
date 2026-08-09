"""Writes and reads over Aggregates (ticket 30): presentation summaries
whose constituents stay retrievable. A bot aggregate stores a scope — the
fill source it summarises, optionally one symbol of it — because derived
positions are wiped and rebuilt wholesale (ADR-0009) and a stored member
list would not survive the rebuild; the scope does. A dust sweep's members
are Transactions wearing `aggregate_id`, released by SET NULL when the
aggregate is disbanded.

Whether a set of Transactions forms a dust sweep is the service's decision,
judged before anything reaches here.
"""

from collections.abc import Sequence

from sqlalchemy import Connection, Engine, Row, text


def scope_covers(
    *, scope_source: str, scope_symbol: str | None, source: str | None, symbol: str
) -> bool:
    """Whether a bot aggregate's scope covers a record wearing this source
    and symbol — a manual position wears no source and is never a bot's.
    The one membership rule, shared by the summaries and the futures
    overview's marking."""
    return source == scope_source and scope_symbol in (None, symbol)


def insert_bot(connection: Connection, *, label: str, source: str, symbol: str | None) -> int:
    return connection.execute(
        text(
            "INSERT INTO aggregate (kind, label, futures_source, futures_symbol)"
            " VALUES ('bot', :label, :source, :symbol) RETURNING id"
        ),
        {"label": label, "source": source, "symbol": symbol},
    ).scalar_one()


def insert_dust_sweep(connection: Connection, *, label: str) -> int:
    return connection.execute(
        text("INSERT INTO aggregate (kind, label) VALUES ('dust_sweep', :label) RETURNING id"),
        {"label": label},
    ).scalar_one()


def overlapping_bot_scope(connection: Connection, *, source: str, symbol: str | None) -> Row | None:
    """An existing bot aggregate this scope would overlap: the same source,
    where either side covers the whole of it or both name the same symbol —
    two summaries over one stream would present its figures twice."""
    return connection.execute(
        text(
            "SELECT id, label FROM aggregate WHERE kind = 'bot'"
            " AND futures_source = :source"
            " AND (futures_symbol IS NULL OR CAST(:symbol AS text) IS NULL"
            " OR futures_symbol = :symbol)"
            " LIMIT 1"
        ),
        {"source": source, "symbol": symbol},
    ).one_or_none()


def tag_transactions(
    connection: Connection, aggregate_id: int, transaction_ids: Sequence[int]
) -> None:
    connection.execute(
        text("UPDATE transaction SET aggregate_id = :aggregate_id WHERE id = ANY(:ids)"),
        {"aggregate_id": aggregate_id, "ids": list(transaction_ids)},
    )


def constituent_candidates(connection: Connection, transaction_ids: Sequence[int]) -> list[Row]:
    """What judging a dust sweep needs of each named Transaction: its type,
    any aggregate it already belongs to, and its in-legs."""
    return list(
        connection.execute(
            text(
                "SELECT t.id, t.type, t.aggregate_id, l.id AS leg_id, l.account_id,"
                " l.instrument_id, l.quantity"
                " FROM transaction t"
                " LEFT JOIN transaction_leg l ON l.transaction_id = t.id AND l.role = 'in'"
                " WHERE t.id = ANY(:ids) ORDER BY t.id, l.id"
            ),
            {"ids": list(transaction_ids)},
        ).all()
    )


def delete(engine: Engine, aggregate_id: int) -> bool:
    """Disband: members are released by the SET NULL constraint; nothing a
    summary pointed at is touched."""
    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM aggregate WHERE id = :aggregate_id"),
            {"aggregate_id": aggregate_id},
        )
    return removed.rowcount == 1


_COLUMNS = "id, kind, label, futures_source, futures_symbol"


def rows(connection: Connection) -> list[Row]:
    return list(connection.execute(text(f"SELECT {_COLUMNS} FROM aggregate ORDER BY id")).all())


def get(connection: Connection, aggregate_id: int) -> Row | None:
    return connection.execute(
        text(f"SELECT {_COLUMNS} FROM aggregate WHERE id = :aggregate_id"),
        {"aggregate_id": aggregate_id},
    ).one_or_none()


def bot_rows(connection: Connection) -> list[Row]:
    return list(
        connection.execute(
            text(f"SELECT {_COLUMNS} FROM aggregate WHERE kind = 'bot' ORDER BY id")
        ).all()
    )


def fill_counts(connection: Connection) -> list[Row]:
    """Fill counts per (source, symbol) — the granularity every bot scope is
    a union of."""
    return list(
        connection.execute(
            text("SELECT source, symbol, count(*)::int AS fills FROM futures_fill GROUP BY 1, 2")
        ).all()
    )


def fills_for_scope(connection: Connection, *, source: str, symbol: str | None) -> list[Row]:
    """A bot aggregate's constituent fills, in derivation order."""
    return list(
        connection.execute(
            text(
                "SELECT id, source, external_id, account_id, symbol, side, price, size, fee,"
                " settlement_instrument_id, occurred_at, position_side, reduce_only, realized,"
                " inverse FROM futures_fill"
                " WHERE source = :source AND (CAST(:symbol AS text) IS NULL OR symbol = :symbol)"
                " ORDER BY occurred_at, id"
            ),
            {"source": source, "symbol": symbol},
        ).all()
    )


def sweep_member_rows(connection: Connection) -> list[Row]:
    """Every dust-sweep member's received side, one row per in-leg — what
    the summaries derive from, honest to the ledger as it stands now rather
    than as it stood when the sweep was recorded."""
    return list(
        connection.execute(
            text(
                "SELECT t.aggregate_id, t.id, t.occurred_at, l.account_id, l.instrument_id,"
                " l.quantity"
                " FROM transaction t"
                " LEFT JOIN transaction_leg l ON l.transaction_id = t.id AND l.role = 'in'"
                " WHERE t.aggregate_id IS NOT NULL ORDER BY t.aggregate_id, t.id, l.id"
            )
        ).all()
    )
