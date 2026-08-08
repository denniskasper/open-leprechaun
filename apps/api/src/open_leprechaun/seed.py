"""Populate a development database with realistic data: `pnpm db:seed`.

The seed grows with the schema — each ticket that adds a table appends a step
here. Every step must be idempotent: running the seed twice must leave the
database exactly as one run left it, and tests/test_seed.py holds the whole
sequence to that.

It refuses to run outside development, so a mistyped command on a deployed
instance can never write fixture data into a real ledger.
"""

import sys
from collections.abc import Callable, Sequence

from sqlalchemy import Connection, Engine, create_engine, text

from open_leprechaun.settings import Environment, get_settings

SeedStep = Callable[[Connection], None]


def _instruments(connection: Connection) -> None:
    """Instruments that exercise the identity model (ticket 11): native coins,
    two tokens sharing a ticker — the v1 collision case — and a security with
    a Listing and lookup aliases.

    Idempotent through the schema's own identity constraints: a bare
    ON CONFLICT DO NOTHING lets the unique indexes decide what already exists.
    """
    instrument_rows = [
        ("crypto", "native", "BTC", "Bitcoin", "bitcoin", None, None),
        ("crypto", "native", "SOL", "Solana", "solana", None, None),
        (
            "crypto",
            "token",
            "UNI",
            "Uniswap",
            "ethereum",
            "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",
            None,
        ),
        (
            "crypto",
            "token",
            "UNI",
            "Unicorn Farm",
            "bsc",
            "0xb5c578947de0fd71303f71f2c3d41767438bd0de",
            None,
        ),
        (
            "security",
            "etf",
            "EUNL",
            "iShares Core MSCI World UCITS ETF",
            None,
            None,
            "IE00B4L5Y983",
        ),
    ]
    for family, type_, symbol, name, chain, contract_address, isin in instrument_rows:
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, chain,"
                " contract_address, isin)"
                " VALUES (:family, :type, :symbol, :name, :chain, :contract_address, :isin)"
                " ON CONFLICT DO NOTHING"
            ),
            {
                "family": family,
                "type": type_,
                "symbol": symbol,
                "name": name,
                "chain": chain,
                "contract_address": contract_address,
                "isin": isin,
            },
        )
    # The identifier history every Instrument keeps from birth: a token's
    # contract, a native coin's symbol, a security's ISIN.
    connection.execute(
        text(
            "INSERT INTO instrument_identifier (instrument_id, kind, value)"
            " SELECT id, 'contract_address', contract_address FROM instrument"
            " WHERE contract_address IS NOT NULL"
            " ON CONFLICT DO NOTHING"
        )
    )
    connection.execute(
        text(
            "INSERT INTO instrument_identifier (instrument_id, kind, value)"
            " SELECT id, 'symbol', symbol FROM instrument"
            " WHERE family = 'crypto' AND type = 'native'"
            " ON CONFLICT DO NOTHING"
        )
    )
    fund = {"isin": "IE00B4L5Y983"}
    connection.execute(
        text(
            "INSERT INTO listing (instrument_id, venue, quote_currency)"
            " SELECT id, 'XETRA', 'EUR' FROM instrument WHERE isin = :isin"
            " ON CONFLICT DO NOTHING"
        ),
        fund,
    )
    for kind, value in [("isin", "IE00B4L5Y983"), ("wkn", "A0RPWH"), ("ticker", "EUNL")]:
        connection.execute(
            text(
                "INSERT INTO instrument_identifier (instrument_id, kind, value)"
                " SELECT id, :kind, :value FROM instrument WHERE isin = :isin"
                " ON CONFLICT DO NOTHING"
            ),
            {"kind": kind, "value": value, **fund},
        )


STEPS: Sequence[SeedStep] = (_instruments,)
"""One entry per seeded slice of the schema, in dependency order."""


def seed(engine: Engine, steps: Sequence[SeedStep] = STEPS) -> None:
    """Apply every step in one transaction, so a failed seed leaves nothing."""
    with engine.begin() as connection:
        for step in steps:
            step(connection)


def main() -> None:
    settings = get_settings()
    if settings.environment is not Environment.development:
        sys.exit(
            f"Refusing to seed: this instance is {settings.environment}, and the seed "
            "writes fixture data meant only for development."
        )
    engine = create_engine(settings.database_url)
    try:
        seed(engine)
    finally:
        engine.dispose()
    print(f"Seeded the development database ({len(STEPS)} steps).")


if __name__ == "__main__":
    main()
