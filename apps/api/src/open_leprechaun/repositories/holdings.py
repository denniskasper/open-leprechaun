"""Reads the holdings view (ticket 20) needs beyond the derivation's own
inputs: where each Account sits, and what the providers last knew each
crypto Instrument (ticket 18) and security (ticket 45) to be worth.

Every function takes the service's Connection rather than the Engine, like
repositories/lots — the portfolio is assembled on one snapshot, so a position
and the lots behind it describe the same instant of the ledger.
"""

from sqlalchemy import Connection, Row, text


def account_rows(connection: Connection) -> list[Row]:
    """Every Account with its Platform — the location a position names, the
    kind custody is judged from, and the extra software needed to reach it."""
    return list(
        connection.execute(
            text(
                "SELECT account.id, account.name, account.access_software,"
                " platform.name AS platform_name, platform.kind AS platform_kind"
                " FROM account JOIN platform ON platform.id = account.platform_id"
            )
        ).all()
    )


def price_rows(connection: Connection) -> list[Row]:
    """The last known price per crypto Instrument and security, with its
    source and age — one store row per Instrument either way, so the union
    cannot collide. The request path values from the store alone; refreshing
    a store is its own endpoint (tickets 18, 45)."""
    return list(
        connection.execute(
            text(
                "SELECT instrument_id, price_eur, source, as_of FROM crypto_price"
                " UNION ALL"
                " SELECT instrument_id, price_eur, source, as_of FROM security_price"
            )
        ).all()
    )
