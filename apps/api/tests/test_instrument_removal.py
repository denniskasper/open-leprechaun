"""Removing an Instrument (issue 9): the repair for a mistyped identity, which
cannot be edited because it is what the Instrument is (ADR-0010).

An Instrument may be removed only while nothing in the ledger refers to it.
What the Admin declared about it goes with it, and so do its stored prices;
history never does, and the numéraire never goes at all. The seam is the
HTTP endpoint through the app, against real Postgres.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.repositories import (
    corporate_actions,
    crypto_prices,
    delegations,
    fund_redemption_values,
    futures,
    instruments,
    platforms,
    provider_status,
    security_prices,
    stances,
)
from open_leprechaun.repositories.corporate_actions import CorporateAction
from open_leprechaun.repositories.transactions import CapitalIncome, Leg, create_transaction

UNISWAP_CONTRACT = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"


def _a_token(db) -> int:
    return instruments.create_crypto_token(
        db, symbol="UNI", name="Uniswap", chain="ethereum", contract_address=UNISWAP_CONTRACT
    )


def _a_native_coin(db) -> int:
    return instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")


def _a_currency(db) -> int:
    return instruments.create_cash(db, symbol="USD", name="US Dollar")


def _a_security(db) -> int:
    return instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )


def _instrument_ids(client) -> list[int]:
    return [instrument["id"] for instrument in client.get("/api/instruments").json()]


@pytest.mark.parametrize("create", [_a_token, _a_native_coin, _a_currency, _a_security])
def test_the_api_removes_an_unused_instrument_of_every_family(client, db, create):
    """One rule through one route: a token, a native coin, cash and a
    security nothing refers to are taken back, and gone is not found."""
    instrument_id = create(db)
    kept = _a_native_coin(db) if create is not _a_native_coin else _a_currency(db)

    assert client.delete(f"/api/instruments/{instrument_id}").status_code == 204
    assert _instrument_ids(client) == [kept]
    gone = client.delete(f"/api/instruments/{instrument_id}")
    assert gone.status_code == 404
    assert gone.json()["detail"] == "No such Instrument."


def test_the_numeraire_is_refused_with_its_own_reason(client, db):
    """The currency every figure is expressed in never disappears — even
    with nothing recorded in it, so its reason is not one of use."""
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)

    refused = client.delete(f"/api/instruments/{eur}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == "EUR is the numéraire, so it stays for good."
    assert _instrument_ids(client) == [eur]


# Every table that refers to an Instrument, whether it holds it or goes with it.
_AROUND_AN_INSTRUMENT = (
    "transaction_leg",
    "futures_fill",
    "funding_payment",
    "futures_position",
    "capital_income",
    "corporate_action",
    "instrument_stance",
    "listing",
    "instrument_identifier",
    "staking_delegation",
    "fund_redemption_value",
    "crypto_price",
    "crypto_daily_close",
    "security_price",
    "security_daily_close",
    "provider_affected_instrument",
    "tax_lot",
)

AT = datetime(2031, 3, 14, 12, 0, tzinfo=UTC)


def _ledger(db) -> dict[str, int]:
    """How many rows each table around an Instrument holds — what a refused
    removal must leave exactly as it found."""
    with db.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in _AROUND_AN_INSTRUMENT
        }


def _an_account(db) -> int:
    """The one Account every record lands in, opened on first use."""
    opened = platforms.list_accounts(db)
    if opened:
        return opened[0].id
    platform_id = platforms.create_platform(db, name="OKX", kind="exchange")
    return platforms.create_account(db, platform_id, name="Trading")


def _a_leg(db, instrument_id):
    create_transaction(
        db,
        type="transfer_in",
        occurred_at=AT,
        note=None,
        legs=[
            Leg(
                account_id=_an_account(db),
                instrument_id=instrument_id,
                role="in",
                quantity=Decimal("1.5"),
            )
        ],
    )


def _a_futures_fill(db, instrument_id):
    with db.begin() as connection:
        futures.store_fills(
            connection,
            "okx:futures",
            [
                futures.NormalizedFill(
                    external_id="fill-1",
                    account_id=_an_account(db),
                    symbol="BTC-USD-SWAP",
                    side="buy",
                    price=Decimal("50000"),
                    size=Decimal("0.1"),
                    fee=Decimal("0.5"),
                    settlement_instrument_id=instrument_id,
                    occurred_at=AT,
                )
            ],
        )


def _a_funding_payment(db, instrument_id):
    with db.begin() as connection:
        futures.store_funding(
            connection,
            "okx:futures",
            [
                futures.NormalizedFunding(
                    external_id="funding-1",
                    account_id=_an_account(db),
                    symbol="BTC-USD-SWAP",
                    amount=Decimal("-0.25"),
                    settlement_instrument_id=instrument_id,
                    occurred_at=AT,
                )
            ],
        )


def _a_position(db, instrument_id) -> futures.FuturesPosition:
    return futures.FuturesPosition(
        account_id=_an_account(db),
        symbol="BTC-USD-SWAP",
        side="long",
        quantity=Decimal("0.1"),
        settlement_instrument_id=instrument_id,
        opened_at=AT,
        closed_at=None,
        realized=Decimal(0),
        fees=Decimal(0),
    )


def _a_manual_futures_position(db, instrument_id):
    with db.begin() as connection:
        futures.insert_manual(connection, _a_position(db, instrument_id))


def _a_derived_futures_position(db, instrument_id):
    with db.begin() as connection:
        futures.replace_derived(connection, "okx:futures", [_a_position(db, instrument_id)], [])


def _capital_income_it_paid(db, instrument_id):
    """A dividend arrives in cash; the security that paid it is named beside
    the legs, not in them."""
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    create_transaction(
        db,
        type="dividend",
        occurred_at=AT,
        note=None,
        legs=[Leg(account_id=_an_account(db), instrument_id=usd, role="in", quantity=Decimal("3"))],
        capital_income=CapitalIncome(paying_instrument_id=instrument_id),
    )


def _a_corporate_action_on_it(db, instrument_id):
    corporate_actions.create(
        db,
        CorporateAction(
            kind="split",
            instrument_id=instrument_id,
            effective_at=AT,
            units_new=Decimal(2),
            units_old=Decimal(1),
        ),
    )


def _a_corporate_action_into_it(db, instrument_id):
    absorbed = instruments.create_security(
        db, symbol="OLD", name="Absorbed AG", type="share", isin="DE000A0D9PT0"
    )
    corporate_actions.create(
        db,
        CorporateAction(
            kind="merger",
            instrument_id=absorbed,
            effective_at=AT,
            units_new=Decimal(1),
            units_old=Decimal(3),
            target_instrument_id=instrument_id,
        ),
    )


@pytest.mark.parametrize(
    ("create", "record", "named"),
    [
        (_a_native_coin, _a_leg, "transactions"),
        (_a_currency, _a_futures_fill, "futures fills"),
        (_a_currency, _a_funding_payment, "funding payments"),
        (_a_currency, _a_manual_futures_position, "futures positions"),
        (_a_currency, _a_derived_futures_position, "futures positions"),
        (_a_security, _capital_income_it_paid, "capital income"),
        (_a_security, _a_corporate_action_on_it, "corporate actions"),
        (_a_security, _a_corporate_action_into_it, "corporate actions"),
    ],
)
def test_an_instrument_the_ledger_refers_to_stays_and_the_refusal_names_the_kind(
    client, db, create, record, named
):
    """History never goes: anything recorded against the Instrument keeps it
    for good, the refusal says what kind of record that is, and trying
    changes nothing."""
    instrument_id = create(db)
    record(db, instrument_id)
    listed, around = client.get("/api/instruments").json(), _ledger(db)

    refused = client.delete(f"/api/instruments/{instrument_id}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == f"This Instrument stays for good: it is recorded in {named}."
    assert client.get("/api/instruments").json() == listed
    assert _ledger(db) == around


def test_every_kind_of_record_that_keeps_an_instrument_is_named(client, db):
    security = _a_security(db)
    _a_leg(db, security)
    _a_corporate_action_on_it(db, security)

    refused = client.delete(f"/api/instruments/{security}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Instrument stays for good: it is recorded in transactions and corporate actions."
    )


def test_a_refusal_never_states_how_many_records_keep_the_instrument(client, db):
    """Many records of several kinds still read as kinds alone — the
    message carries no figure from the Admin's accounts."""
    usd = _a_currency(db)
    for _ in range(3):
        _a_leg(db, usd)
    _a_futures_fill(db, usd)
    _a_funding_payment(db, usd)
    _a_manual_futures_position(db, usd)

    refused = client.delete(f"/api/instruments/{usd}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Instrument stays for good: it is recorded in transactions, futures fills,"
        " funding payments and futures positions."
    )
    assert not any(character.isdigit() for character in refused.json()["detail"])


# What goes with an Instrument, each table keyed on it by the same column.
_GOES_WITH_IT = (
    "instrument_stance",
    "listing",
    "instrument_identifier",
    "staking_delegation",
    "fund_redemption_value",
    "crypto_price",
    "crypto_daily_close",
    "security_price",
    "security_daily_close",
    "provider_affected_instrument",
    "tax_lot",
)


def _a_fund(db, isin: str) -> int:
    return instruments.create_security(
        db,
        symbol=isin[-4:],
        name=f"Synthetic Fund {isin}",
        type="etf",
        isin=isin,
        wkn=f"W{isin[-5:]}",
        ticker=f"T{isin[-3:]}",
        venue="XETRA",
        quote_currency="EUR",
    )


def _everything_declared_and_stored_about(db, instrument_id):
    """A Stance at an Account and everywhere, a second Listing, a staking
    marker, a year of redemption values, prices and closes of both kinds —
    and a Tax Lot left in the materialisation."""
    account_id = _an_account(db)
    assert stances.classify(db, instrument_id, stance="kept", account_id=account_id) == []
    assert stances.classify(db, instrument_id, stance="dangerous") == []
    assert instruments.add_listing(db, instrument_id, venue="Tradegate", quote_currency="EUR")
    assert delegations.mark(db, instrument_id=instrument_id, account_id=account_id, note=None)
    fund_redemption_values.upsert_value(
        db,
        instrument_id=instrument_id,
        year=2030,
        start_of_year_eur=Decimal("100"),
        end_of_year_eur=Decimal("110"),
        distributions_eur=Decimal("0"),
        source="Synthetic factsheet",
    )
    crypto_prices.store_quote(
        db, instrument_id=instrument_id, price_eur=Decimal("1"), source="coingecko", as_of=AT
    )
    crypto_prices.store_daily_closes(
        db, instrument_id, source="coingecko", closes=[(date(2031, 3, 13), Decimal("1"))]
    )
    security_prices.store_quote(
        db,
        instrument_id=instrument_id,
        price_eur=Decimal("105"),
        quote_currency="EUR",
        venue="XETRA",
        source="onvista",
        as_of=AT,
    )
    security_prices.store_daily_closes(
        db, instrument_id, source="onvista", closes=[(date(2031, 3, 13), Decimal("105"))]
    )
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tax_lot (account_id, instrument_id, acquired_at, quantity,"
                " basis_source, ordinal) VALUES (:account, :instrument, :at, 1, 'market_value', 0)"
            ),
            {"account": account_id, "instrument": instrument_id, "at": AT},
        )


def _rows_about(db, instrument_id) -> dict[str, int]:
    with db.connect() as connection:
        return {
            table: connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE instrument_id = :instrument_id"),
                {"instrument_id": instrument_id},
            ).scalar_one()
            for table in _GOES_WITH_IT
        }


def test_what_was_declared_and_stored_about_an_unused_instrument_goes_with_it(client, db):
    """Its Stances, Listings, identifier history, staking marker, redemption
    values, prices, closes, provider mentions and Tax Lots neither hold the
    Instrument nor outlive it — and the same rows of another stay put."""
    doomed, bystander = _a_fund(db, "ZZ0000000017"), _a_fund(db, "ZZ0000000025")
    for instrument_id in (doomed, bystander):
        _everything_declared_and_stored_about(db, instrument_id)
    provider_status.record_failure(
        db, "onvista", condition="outage", error="Synthetic outage.", at=AT
    )
    provider_status.replace_affected(db, "onvista", {doomed, bystander})
    assert all(_rows_about(db, doomed).values())
    untouched = _rows_about(db, bystander)

    assert client.delete(f"/api/instruments/{doomed}").status_code == 204

    assert _rows_about(db, doomed) == dict.fromkeys(_GOES_WITH_IT, 0)
    assert _rows_about(db, bystander) == untouched
    assert _instrument_ids(client) == [bystander]


@pytest.mark.parametrize(
    ("route", "identity"),
    [
        (
            "/api/instruments",
            {
                "kind": "token",
                "symbol": "UNI",
                "name": "Uniswap",
                "chain": "ethereum",
                "contract_address": UNISWAP_CONTRACT,
            },
        ),
        ("/api/instruments", {"kind": "native", "symbol": "SOL", "name": "Solana", "chain": "sol"}),
        ("/api/instruments", {"kind": "cash", "symbol": "USD", "name": "US Dollar"}),
        (
            "/api/securities",
            {"isin": "IE00B4L5Y983", "name": "Synthetic World", "symbol": "EUNL", "type": "etf"},
        ),
    ],
)
def test_a_removed_identity_can_be_added_again_straight_away(client, db, route, identity):
    """Removal is the first half of the repair; the second is adding the
    right Instrument — under the same symbol or ISIN if need be."""
    mistaken = client.post(route, json=identity)
    assert mistaken.status_code == 201

    assert client.delete(f"/api/instruments/{mistaken.json()['id']}").status_code == 204

    again = client.post(route, json=identity)
    assert again.status_code == 201
    assert _instrument_ids(client) == [again.json()["id"]]
