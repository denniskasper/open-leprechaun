"""Writes and reads over what a fund published for one unit in one calendar
year (ticket 53): its first and last redemption price and its distributions,
in EUR, each row with the source it was taken from. Entering a row is an
upsert — the store holds one truth per (fund, year), corrected together with
the citation that corrected it.
"""

from decimal import Decimal

from sqlalchemy import Engine, Row, text


def list_values(engine: Engine) -> list[Row]:
    """Every entered row, newest year first within each fund."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT instrument_id, year, start_of_year_eur, end_of_year_eur,"
                    " distributions_eur, source FROM fund_redemption_value"
                    " ORDER BY instrument_id, year DESC"
                )
            ).all()
        )


def list_funds(engine: Engine) -> list[Row]:
    """Every fund the ledger knows — what a redemption value can be entered
    for."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, symbol, name, isin FROM instrument"
                    " WHERE family = 'security' AND type IN ('etf', 'fund')"
                    " ORDER BY symbol, id"
                )
            ).all()
        )


def is_fund(engine: Engine, instrument_id: int) -> bool:
    """Whether the Instrument exists and is a fund — the only thing a
    redemption value can be entered for."""
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT 1 FROM instrument WHERE id = :instrument_id"
                    " AND family = 'security' AND type IN ('etf', 'fund')"
                ),
                {"instrument_id": instrument_id},
            ).scalar_one_or_none()
            is not None
        )


def upsert_value(
    engine: Engine,
    *,
    instrument_id: int,
    year: int,
    start_of_year_eur: Decimal,
    end_of_year_eur: Decimal,
    distributions_eur: Decimal,
    source: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fund_redemption_value (instrument_id, year, start_of_year_eur,"
                " end_of_year_eur, distributions_eur, source)"
                " VALUES (:instrument_id, :year, :start_of_year_eur, :end_of_year_eur,"
                " :distributions_eur, :source)"
                " ON CONFLICT (instrument_id, year) DO UPDATE SET"
                " start_of_year_eur = excluded.start_of_year_eur,"
                " end_of_year_eur = excluded.end_of_year_eur,"
                " distributions_eur = excluded.distributions_eur, source = excluded.source"
            ),
            {
                "instrument_id": instrument_id,
                "year": year,
                "start_of_year_eur": start_of_year_eur,
                "end_of_year_eur": end_of_year_eur,
                "distributions_eur": distributions_eur,
                "source": source,
            },
        )


def delete_value(engine: Engine, *, instrument_id: int, year: int) -> bool:
    """Unset one fund's year. False when there was nothing to unset."""
    with engine.begin() as connection:
        removed = connection.execute(
            text(
                "DELETE FROM fund_redemption_value"
                " WHERE instrument_id = :instrument_id AND year = :year"
            ),
            {"instrument_id": instrument_id, "year": year},
        )
    return removed.rowcount == 1
