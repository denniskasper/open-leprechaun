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
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Connection, Engine, create_engine, text

from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.services import futures
from open_leprechaun.settings import Environment, get_settings

SeedStep = Callable[[Connection], None]


def _instruments(connection: Connection) -> None:
    """Instruments that exercise the identity model (ticket 11): native coins,
    two tokens sharing a ticker — the v1 collision case — a stablecoin whose
    peg routes its EUR value to the daily reference rate (ticket 17), and a
    security with a Listing and lookup aliases.

    Idempotent through the schema's own identity constraints: a bare
    ON CONFLICT DO NOTHING lets the unique indexes decide what already exists.
    """
    instrument_rows = [
        ("crypto", "native", "BTC", "Bitcoin", "bitcoin", None, None, None),
        ("crypto", "native", "SOL", "Solana", "solana", None, None, None),
        (
            "crypto",
            "token",
            "UNI",
            "Uniswap",
            "ethereum",
            "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",
            None,
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
            None,
        ),
        (
            "crypto",
            "token",
            "USDT",
            "Tether USD",
            "ethereum",
            "0xdac17f958d2ee523a2206206994597c13d831ec7",
            None,
            "USD",
        ),
        (
            "security",
            "etf",
            "EUNL",
            "iShares Core MSCI World UCITS ETF",
            None,
            None,
            "IE00B4L5Y983",
            None,
        ),
    ]
    for family, type_, symbol, name, chain, contract_address, isin, pegged in instrument_rows:
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, chain,"
                " contract_address, isin, pegged_currency)"
                " VALUES (:family, :type, :symbol, :name, :chain, :contract_address, :isin,"
                " :pegged_currency)"
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
                "pegged_currency": pegged,
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


def _cash(connection: Connection) -> None:
    """A non-EUR currency (ticket 12): an ordinary asset whose movement is a
    disposal, next to the EUR numéraire the migration chain itself provides.
    Cash keys on its code, so ON CONFLICT DO NOTHING keeps this idempotent."""
    connection.execute(
        text(
            "INSERT INTO instrument (family, type, symbol, name)"
            " VALUES ('cash', 'fiat', 'USD', 'US Dollar')"
            " ON CONFLICT DO NOTHING"
        )
    )
    connection.execute(
        text(
            "INSERT INTO instrument_identifier (instrument_id, kind, value)"
            " SELECT id, 'symbol', symbol FROM instrument WHERE family = 'cash'"
            " ON CONFLICT DO NOTHING"
        )
    )


def _platforms(connection: Connection) -> None:
    """One Platform of every kind with representative Accounts (ticket 10),
    including two Accounts on one device and chain — the evidence-scoped FIFO
    boundary the model must permit. Names are unique per Platform and
    Platforms per name, so ON CONFLICT DO NOTHING keeps this idempotent."""
    # The broker arrives with its Depot semantics declared (ticket 43):
    # withholding at source with a demonstration exemption order lodged, so a
    # Depot can hold positions from day one and the settings screen has the
    # declared state to show.
    platform_rows = [
        ("Kraken", "exchange", None, None),
        ("BitBox02", "cold_storage", None, None),
        ("Phantom", "software_wallet", None, None),
        ("Scalable Capital", "broker", "at_source", "1000"),
        ("Sparkasse", "bank", None, None),
    ]
    for name, kind, withholding, exemption_order_eur in platform_rows:
        connection.execute(
            text(
                "INSERT INTO platform (name, kind, withholding, exemption_order_eur)"
                " VALUES (:name, :kind, :withholding, :exemption_order_eur)"
                " ON CONFLICT DO NOTHING"
            ),
            {
                "name": name,
                "kind": kind,
                "withholding": withholding,
                "exemption_order_eur": exemption_order_eur,
            },
        )
    account_rows = [
        ("Kraken", "Main", None, None, None, None),
        ("BitBox02", "Savings", "bitcoin", None, "BitBoxApp", None),
        ("BitBox02", "Spending", "bitcoin", None, "BitBoxApp", None),
        (
            "Phantom",
            "Hot wallet",
            "solana",
            "F1xt5reSo1anaAddressExamp1eOn1yNotRea1111111",
            None,
            None,
        ),
        ("Scalable Capital", "Depot", None, "1234567890", None, "EUR"),
        ("Sparkasse", "Giro", None, "DE02120300000000202051", "chipTAN app", None),
    ]
    for (
        platform_name,
        name,
        chain,
        external_reference,
        access_software,
        base_currency,
    ) in account_rows:
        connection.execute(
            text(
                "INSERT INTO account"
                " (platform_id, name, chain, external_reference, access_software, base_currency)"
                " SELECT id, :name, :chain, :external_reference, :access_software, :base_currency"
                " FROM platform WHERE name = :platform_name"
                " ON CONFLICT DO NOTHING"
            ),
            {
                "platform_name": platform_name,
                "name": name,
                "chain": chain,
                "external_reference": external_reference,
                "access_software": access_software,
                "base_currency": base_currency,
            },
        )


def _transactions(connection: Connection) -> None:
    """A ledger with every shape ticket 13 names: a trade carrying both sides
    and a fee in a third asset, income, and a transfer that is not assumed to
    be a purchase. Deliberately built on the seed's own instruments — USD,
    not the EUR the migration chain mints — so the step stands on the steps
    before it alone. A Transaction has no natural identity, so each is keyed
    for idempotency on its type and instant: inserted only when that pair is
    absent, legs riding along in the same pass."""
    events = [
        (
            "trade",
            "2026-01-05T10:30:00+00:00",
            "USD for BTC, fee taken in SOL",
            None,
            None,
            [
                ("Kraken", "Main", "USD", "out", "250.00", None),
                ("Kraken", "Main", "BTC", "in", "0.004", None),
                ("Kraken", "Main", "SOL", "fee", "0.02", 1),
            ],
        ),
        (
            "staking_reward",
            "2026-01-20T00:00:00+00:00",
            None,
            None,
            None,
            [("Phantom", "Hot wallet", "SOL", "in", "0.35", None)],
        ),
        # A self-transfer's two sides (ticket 16), each recorded where it
        # happened and left unlinked — so the development matching screen has
        # a proposal waiting on the Admin's decision.
        (
            "transfer_out",
            "2026-02-02T18:30:00+00:00",
            "Withdrawn to cold storage",
            None,
            None,
            [("Kraken", "Main", "BTC", "out", "0.004", None)],
        ),
        (
            "transfer_in",
            "2026-02-02T18:45:00+00:00",
            "Moved from the exchange",
            None,
            None,
            [("BitBox02", "Savings", "BTC", "in", "0.004", None)],
        ),
        # A position that predates the ledger's history (ticket 15): the
        # date-known variant, so the acquisition date is used as given and
        # only the basis is a declared estimate.
        (
            "opening_balance",
            "2021-04-15T00:00:00+00:00",
            "Held since before the export window",
            "basis",
            "700.00",
            [("BitBox02", "Savings", "BTC", "in", "0.02", None)],
        ),
    ]
    for type_, occurred_at, note, reconstructed, estimated_basis_eur, legs in events:
        transaction_id = connection.execute(
            text(
                "INSERT INTO transaction"
                " (type, occurred_at, note, reconstructed, estimated_basis_eur)"
                " SELECT :type, CAST(:occurred_at AS timestamptz), :note, :reconstructed,"
                " CAST(:estimated_basis_eur AS numeric)"
                " WHERE NOT EXISTS (SELECT 1 FROM transaction WHERE type = :type"
                " AND occurred_at = CAST(:occurred_at AS timestamptz))"
                " RETURNING id"
            ),
            {
                "type": type_,
                "occurred_at": occurred_at,
                "note": note,
                "reconstructed": reconstructed,
                "estimated_basis_eur": estimated_basis_eur,
            },
        ).scalar_one_or_none()
        if transaction_id is None:
            continue
        leg_ids = [
            connection.execute(
                text(
                    "INSERT INTO transaction_leg"
                    " (transaction_id, account_id, instrument_id, role, quantity)"
                    " SELECT :transaction_id, account.id, instrument.id, :role,"
                    " CAST(:quantity AS numeric)"
                    " FROM account JOIN platform ON platform.id = account.platform_id,"
                    " instrument"
                    " WHERE platform.name = :platform AND account.name = :account"
                    " AND instrument.symbol = :symbol"
                    " RETURNING id"
                ),
                {
                    "transaction_id": transaction_id,
                    "platform": platform,
                    "account": account,
                    "symbol": symbol,
                    "role": role,
                    "quantity": quantity,
                },
            ).scalar_one()
            for platform, account, symbol, role, quantity, _ in legs
        ]
        for (*_, charged_against), leg_id in zip(legs, leg_ids, strict=True):
            if charged_against is not None:
                connection.execute(
                    text(
                        "UPDATE transaction_leg SET charged_against_leg_id = :target"
                        " WHERE id = :leg_id"
                    ),
                    {"target": leg_ids[charged_against], "leg_id": leg_id},
                )


def _stances(connection: Connection) -> None:
    """The stance landscape ticket 14 describes: the genuine holdings kept at
    the Accounts that hold them, and one same-ticker spam token — sprayed
    unasked into the hot wallet — left unacknowledged, so the development
    inbox has an arrival waiting on a decision.

    Idempotent like the rest: identity constraints arbitrate the instrument
    and the stances, the (type, occurred_at) key arbitrates the inflow."""
    connection.execute(
        text(
            "INSERT INTO instrument (family, type, symbol, name, chain, contract_address)"
            " VALUES ('crypto', 'token', 'USDC', 'USDC Rewards Claim', 'solana',"
            " 'c1aimusdcrewardsexamp1eon1ynotrea1m1nt111111')"
            " ON CONFLICT DO NOTHING"
        )
    )
    connection.execute(
        text(
            "INSERT INTO instrument_identifier (instrument_id, kind, value)"
            " SELECT id, 'contract_address', contract_address FROM instrument"
            " WHERE contract_address IS NOT NULL"
            " ON CONFLICT DO NOTHING"
        )
    )
    # Acknowledging settles a transfer_in as an airdrop or a windfall, so the
    # existence check names all three — a seed re-run after a keep decision
    # must not resurrect the unclassified inflow.
    spam_inflow = connection.execute(
        text(
            "INSERT INTO transaction (type, occurred_at, note)"
            " SELECT 'transfer_in', CAST(:instant AS timestamptz), 'Appeared unasked'"
            " WHERE NOT EXISTS (SELECT 1 FROM transaction"
            " WHERE type IN ('transfer_in', 'airdrop', 'windfall')"
            " AND occurred_at = CAST(:instant AS timestamptz))"
            " RETURNING id"
        ),
        {"instant": "2026-03-01T09:00:00+00:00"},
    ).scalar_one_or_none()
    if spam_inflow is not None:
        connection.execute(
            text(
                "INSERT INTO transaction_leg"
                " (transaction_id, account_id, instrument_id, role, quantity)"
                " SELECT :transaction_id, account.id, instrument.id, 'in',"
                " CAST('1999.75' AS numeric)"
                " FROM account JOIN platform ON platform.id = account.platform_id, instrument"
                " WHERE platform.name = 'Phantom' AND account.name = 'Hot wallet'"
                " AND instrument.name = 'USDC Rewards Claim'"
            ),
            {"transaction_id": spam_inflow},
        )
    kept = [
        ("Kraken", "Main", "Bitcoin"),
        ("Kraken", "Main", "US Dollar"),
        ("Phantom", "Hot wallet", "Solana"),
        ("BitBox02", "Savings", "Bitcoin"),
    ]
    for platform_name, account_name, instrument_name in kept:
        connection.execute(
            text(
                "INSERT INTO instrument_stance (instrument_id, account_id, stance)"
                " SELECT instrument.id, account.id, 'kept'"
                " FROM account JOIN platform ON platform.id = account.platform_id, instrument"
                " WHERE platform.name = :platform_name AND account.name = :account_name"
                " AND instrument.name = :instrument_name"
                " ON CONFLICT (instrument_id, account_id) WHERE account_id IS NOT NULL"
                " DO NOTHING"
            ),
            {
                "platform_name": platform_name,
                "account_name": account_name,
                "instrument_name": instrument_name,
            },
        )


def _delegations(connection: Connection) -> None:
    """The Staking Delegation marker (ticket 22): the hot wallet's SOL —
    already earning the seeded staking reward — marked as delegated, so the
    development instance shows a marker. Informational only; ON CONFLICT
    keeps the Admin's own note over a re-run."""
    connection.execute(
        text(
            "INSERT INTO staking_delegation (instrument_id, account_id, note)"
            " SELECT instrument.id, account.id, 'Everstake'"
            " FROM account JOIN platform ON platform.id = account.platform_id, instrument"
            " WHERE platform.name = 'Phantom' AND account.name = 'Hot wallet'"
            " AND instrument.name = 'Solana'"
            " ON CONFLICT (instrument_id, account_id) DO NOTHING"
        )
    )


def _futures(connection: Connection) -> None:
    """Futures activity of every shape ticket 28 stores: fills that derive
    one closed and one open position, a funding payment inside the closed
    position's interval and one no position can claim, and a manual
    position beside the derived ones. Fills and funding are idempotent by
    their dedupe key; the derived rows are rebuilt wholesale either way, and
    the manual position is keyed on its symbol being absent."""
    account = connection.execute(
        text(
            "SELECT account.id FROM account JOIN platform ON platform.id = account.platform_id"
            " WHERE platform.name = 'Kraken' AND account.name = 'Main'"
        )
    ).scalar_one()
    usdt = connection.execute(
        text("SELECT id FROM instrument WHERE symbol = 'USDT' AND chain = 'ethereum'")
    ).scalar_one()
    fills = [
        futures.NormalizedFill(
            external_id="seed-fill-1",
            account_id=account,
            symbol="BTC-USDT-PERP",
            side="buy",
            price=Decimal("60000"),
            size=Decimal("0.5"),
            fee=Decimal("15"),
            settlement_instrument_id=usdt,
            occurred_at=datetime(2025, 3, 3, 9, 30, tzinfo=UTC),
            inverse=False,
        ),
        futures.NormalizedFill(
            external_id="seed-fill-2",
            account_id=account,
            symbol="BTC-USDT-PERP",
            side="sell",
            price=Decimal("64000"),
            size=Decimal("0.5"),
            fee=Decimal("16"),
            settlement_instrument_id=usdt,
            occurred_at=datetime(2025, 4, 10, 14, 0, tzinfo=UTC),
            realized=Decimal("2000"),
            inverse=False,
        ),
        futures.NormalizedFill(
            external_id="seed-fill-3",
            account_id=account,
            symbol="SOL-USDT-PERP",
            side="sell",
            price=Decimal("150"),
            size=Decimal("20"),
            fee=Decimal("3"),
            settlement_instrument_id=usdt,
            occurred_at=datetime(2025, 5, 2, 8, 0, tzinfo=UTC),
            inverse=False,
        ),
    ]
    funding = [
        futures.NormalizedFunding(
            external_id="seed-funding-1",
            account_id=account,
            symbol="BTC-USDT-PERP",
            amount=Decimal("-4.20"),
            settlement_instrument_id=usdt,
            occurred_at=datetime(2025, 3, 15, 4, 0, tzinfo=UTC),
        ),
        # Before any position was open — surfaced as unattributable.
        futures.NormalizedFunding(
            external_id="seed-funding-2",
            account_id=account,
            symbol="ETH-USDT-PERP",
            amount=Decimal("-1.10"),
            settlement_instrument_id=usdt,
            occurred_at=datetime(2025, 2, 1, 12, 0, tzinfo=UTC),
        ),
    ]
    source = "seed:futures"
    new_fills = futures_repository.store_fills(connection, source, fills)
    new_funding = futures_repository.store_funding(connection, source, funding)
    manual = connection.execute(
        text(
            "INSERT INTO futures_position (origin, source, account_id, symbol, side, quantity,"
            " settlement_instrument_id, opened_at, closed_at, realized, fees)"
            " SELECT 'manual', NULL, :account_id, 'ETH-USDT-PERP', 'long', 1.5,"
            " :settlement_instrument_id, :opened_at, :closed_at, 350, 4"
            " WHERE NOT EXISTS (SELECT 1 FROM futures_position"
            "  WHERE origin = 'manual' AND symbol = 'ETH-USDT-PERP')"
        ),
        {
            "account_id": account,
            "settlement_instrument_id": usdt,
            "opened_at": datetime(2025, 6, 1, 10, 0, tzinfo=UTC),
            "closed_at": datetime(2025, 7, 20, 16, 0, tzinfo=UTC),
        },
    ).rowcount
    # The rebuild swaps the derived rows wholesale, minting fresh ids — run
    # it only when something was actually new, so a second seed run leaves
    # the database exactly as one run left it.
    if new_fills or new_funding or manual:
        futures.rebuild(connection, source)


STEPS: Sequence[SeedStep] = (
    _instruments,
    _cash,
    _platforms,
    _transactions,
    _stances,
    _delegations,
    _futures,
)
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
