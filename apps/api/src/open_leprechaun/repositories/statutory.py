"""Writes and reads over the statutory configuration store (ticket 09). The
schema holds the shape — the key vocabulary, the value bounds, the singleton
election; which keys a complete year requires is the service's knowledge.

Entering a value is an upsert: the store holds one truth per (year, key), and
correcting a value replaces it together with the citation that corrected it.
"""

from decimal import Decimal

from sqlalchemy import Engine, Row, text


def upsert_value(engine: Engine, *, year: int, key: str, value: Decimal, source: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO statutory_value (year, key, value, source)"
                " VALUES (:year, :key, :value, :source)"
                " ON CONFLICT (year, key)"
                " DO UPDATE SET value = excluded.value, source = excluded.source"
            ),
            {"year": year, "key": key, "value": value, "source": source},
        )


def delete_value(engine: Engine, *, year: int, key: str) -> bool:
    """Unset one value. False when there was nothing to unset."""
    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM statutory_value WHERE year = :year AND key = :key"),
            {"year": year, "key": key},
        )
    return removed.rowcount == 1


def list_values(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT year, key, value, source FROM statutory_value ORDER BY year, key")
            ).all()
        )


def election(engine: Engine) -> Row:
    """The single row of Admin choices — born with the schema, always present."""
    with engine.connect() as connection:
        return connection.execute(text("SELECT filing_status, church_tax FROM tax_election")).one()


def set_election(engine: Engine, *, filing_status: str, church_tax: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE tax_election SET filing_status = :filing_status, church_tax = :church_tax"
            ),
            {"filing_status": filing_status, "church_tax": church_tax},
        )
