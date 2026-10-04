"""Reads over what the database itself holds (ticket 55): how large it is and
how much price history is stored. Counts only — nothing here reads a figure.
"""

from sqlalchemy import Engine, Row, text


def measure(engine: Engine) -> Row:
    """The database's size on disk and the rows of stored price history.
    A reference rate counts where one was published: a checked absence is a
    row saying there is no price for that day."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT pg_database_size(current_database()) AS database_bytes,"
                " (SELECT count(*) FROM crypto_daily_close) AS crypto_daily_closes,"
                " (SELECT count(*) FROM security_daily_close) AS security_daily_closes,"
                " (SELECT count(*) FROM reference_rate WHERE rate IS NOT NULL)"
                " AS reference_rates"
            )
        ).one()
