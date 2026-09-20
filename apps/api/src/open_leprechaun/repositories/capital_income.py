"""Reads over what income Transactions declare beyond their legs (ticket 47)
and the treaty limits their Quellensteuer is judged against. The derivation
reads take the caller's Connection, so a producer reads them on one snapshot
with the ledger they describe (repositories/lots)."""

from decimal import Decimal

from sqlalchemy import Connection, Engine, Row, text


def declaration_rows(connection: Connection) -> list[Row]:
    """Every capital-income declaration, keyed by its Transaction."""
    return list(
        connection.execute(
            text(
                "SELECT transaction_id, paying_instrument_id, foreign_withholding,"
                " source_country, kapitalertragsteuer, solidarity_surcharge, church_tax"
                " FROM capital_income"
            )
        ).all()
    )


def withholding_accounts(connection: Connection) -> set[int]:
    """The Accounts whose effective withholding behaviour is `at_source` —
    the Account's own override first, the Platform's word second (ticket
    43). Income there is settled; everywhere else it must be declared."""
    return {
        row.id
        for row in connection.execute(
            text(
                "SELECT account.id FROM account"
                " JOIN platform ON platform.id = account.platform_id"
                " WHERE COALESCE(account.withholding_override, platform.withholding)"
                " = 'at_source'"
            )
        ).all()
    }


def treaty_limit_rows(connection: Connection) -> list[Row]:
    return list(
        connection.execute(
            text("SELECT country, rate, source FROM treaty_limit ORDER BY country")
        ).all()
    )


def list_treaty_limits(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return treaty_limit_rows(connection)


def upsert_treaty_limit(engine: Engine, *, country: str, rate: Decimal, source: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO treaty_limit (country, rate, source)"
                " VALUES (:country, :rate, :source)"
                " ON CONFLICT (country) DO UPDATE SET rate = :rate, source = :source"
            ),
            {"country": country, "rate": rate, "source": source},
        )


def delete_treaty_limit(engine: Engine, country: str) -> bool:
    """False when the country had no limit to remove."""
    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM treaty_limit WHERE country = :country"), {"country": country}
        )
    return removed.rowcount == 1
