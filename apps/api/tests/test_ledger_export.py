"""The ledger export (ticket 56): the ledger handed to an independent tax
tool — CoinTracking — in its documented CSV import format, so a second engine
computes the same year from identical transactions.

The seam is the HTTP API over real Postgres: the file is what the Admin
downloads, and what could not be expressed in it is stated beside it, never
silently dropped.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from open_leprechaun.repositories import instruments, platforms, stances, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services.transactions import TRANSACTION_TYPES

SUMMARY_URL = "/api/ledger-export"
FILE_URL = "/api/ledger-export/cointracking.csv"

# The header CoinTracking documents for a hand-made CSV file, with the four
# optional columns it allows after the date.
HEADER = (
    '"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency",'
    '"Exchange","Trade-Group","Comment","Date",'
    '"Tx-ID","Buy Value in Account Currency","Sell Value in Account Currency","Liquidity pool"'
)

MARCH = datetime(2031, 3, 14, 12, 30, 5, tzinfo=UTC)
JUNE = datetime(2031, 6, 3, 9, 0, tzinfo=UTC)


def _account(db, platform_name="Kraken", kind="exchange", name="Main", **metadata):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name, **metadata)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _coin(db, symbol="BTC", chain="bitcoin"):
    return instruments.create_native_coin(db, symbol=symbol, name=symbol, chain=chain)


def _token(db, symbol, contract_address, chain="ethereum"):
    return instruments.create_crypto_token(
        db, symbol=symbol, name=symbol, chain=chain, contract_address=contract_address
    )


def _record(db, type, legs, *, occurred_at=MARCH, **declarations):
    created = transactions.create_transaction(
        db, type=type, occurred_at=occurred_at, note=None, legs=legs, **declarations
    )
    assert isinstance(created, int)
    return created


def _leg(account, instrument, role, quantity, charged_against=None):
    return Leg(
        account_id=account,
        instrument_id=instrument,
        role=role,
        quantity=Decimal(quantity),
        charged_against=charged_against,
    )


def _file(client):
    response = client.get(FILE_URL)
    assert response.status_code == 200
    return response


def _rows(client):
    """The file's lines after the header."""
    header, *rows = _file(client).text.splitlines()
    assert header == HEADER
    return rows


def _left_out(client):
    response = client.get(SUMMARY_URL)
    assert response.status_code == 200
    return response.json()["left_out"]


def test_a_trade_exports_as_one_row_in_the_documented_format(client, db):
    account = _account(db)
    eur, btc = _eur(db), _coin(db)
    trade = _record(
        db, "trade", [_leg(account, eur, "out", "1500.50"), _leg(account, btc, "in", "0.05")]
    )

    response = _file(client)

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="open-leprechaun-ledger-cointracking.csv"'
    )
    assert response.text == (
        f"{HEADER}\n"
        '"Trade","0.05","BTC","1500.50","EUR","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{trade}-1","","",""\n'
    )


# What each type of the vocabulary becomes in CoinTracking's own list of
# types, stated here from its import documentation rather than read off the
# code. A type missing from this table fails the vocabulary test below.
INFLOWS = {
    "transfer_in": "Deposit",
    "staking_reward": "Staking",
    "lending_interest": "Lending Income",
    "mining_reward": "Mining",
    "airdrop": "Airdrop",
    "windfall": "Airdrop (non taxable)",
    "dividend": "Dividends Income",
    "interest": "Interest Income",
}
OUTFLOWS = {"transfer_out": "Withdrawal", "spend": "Spend"}


@pytest.mark.parametrize(("type", "cointracking_type"), INFLOWS.items())
def test_an_inflow_exports_under_its_cointracking_type(client, db, type, cointracking_type):
    account = _account(db)
    sol = _coin(db, "SOL", "solana")
    received = _record(db, type, [_leg(account, sol, "in", "1.25")])

    assert _rows(client) == [
        f'"{cointracking_type}","1.25","SOL","","","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{received}-1","","",""'
    ]
    assert _left_out(client) == []


@pytest.mark.parametrize(("type", "cointracking_type"), OUTFLOWS.items())
def test_an_outflow_exports_under_its_cointracking_type(client, db, type, cointracking_type):
    account = _account(db)
    sol = _coin(db, "SOL", "solana")
    sent = _record(db, type, [_leg(account, sol, "out", "3")])

    assert _rows(client) == [
        f'"{cointracking_type}","","","3","SOL","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{sent}-1","","",""'
    ]


def test_a_standalone_fee_exports_as_an_other_fee(client, db):
    account = _account(db)
    eur = _eur(db)
    custody = _record(db, "fee", [_leg(account, eur, "fee", "4.90")])

    assert _rows(client) == [
        '"Other Fee","","","4.90","EUR","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{custody}-1","","",""'
    ]


def test_an_opening_balance_exports_as_untaxed_income_at_its_estimated_basis(client, db):
    """Not a purchase and not income: the position existed, at a declared
    basis — which is what the value column states, with nothing sold for it."""
    account = _account(db)
    _eur(db)
    btc = _coin(db)
    opening = _record(
        db,
        "opening_balance",
        [_leg(account, btc, "in", "0.5")],
        reconstructed="basis",
        estimated_basis_eur=Decimal("12000.00"),
    )

    assert _rows(client) == [
        '"Income (non taxable)","0.5","BTC","","","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{opening}-1","12000.00","",""'
    ]


def test_a_distribution_exports_as_dividends_income(client, db):
    account = _account(db, "Scalable", "broker", "Depot")
    with db.begin() as connection:
        connection.exec_driver_sql("UPDATE platform SET withholding = 'none'")
    eur = _eur(db)
    fund = instruments.create_security(
        db, symbol="VWCE", name="An accumulating fund", type="etf", isin="IE00BK5BQT80"
    )
    paid = _record(
        db,
        "distribution",
        [_leg(account, eur, "in", "12.34")],
        capital_income=transactions.CapitalIncome(paying_instrument_id=fund),
    )

    assert _rows(client) == [
        '"Dividends Income","12.34","EUR","","","","","Scalable - Depot","","",'
        f'"14.03.2031 12:30:05","{paid}-1","","",""'
    ]


def test_every_type_in_the_vocabulary_has_a_stated_mapping():
    stated = {*INFLOWS, *OUTFLOWS, "trade", "fee", "opening_balance", "distribution"}

    assert stated == set(TRANSACTION_TYPES)


def test_a_fee_in_the_currency_sold_is_part_of_what_was_sold(client, db):
    """CoinTracking's amounts include the fee and its fee column states it;
    the ledger records it as its own leg, so the two are put together."""
    account = _account(db)
    eur, btc = _eur(db), _coin(db)
    trade = _record(
        db,
        "trade",
        [
            _leg(account, eur, "out", "1000"),
            _leg(account, btc, "in", "0.04"),
            _leg(account, eur, "fee", "2.50", charged_against=1),
        ],
    )

    assert _rows(client) == [
        '"Trade","0.04","BTC","1002.50","EUR","2.50","EUR","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{trade}-1","","",""'
    ]


def test_a_fee_in_the_currency_bought_comes_off_what_was_bought(client, db):
    account = _account(db)
    eur, btc = _eur(db), _coin(db)
    trade = _record(
        db,
        "trade",
        [
            _leg(account, eur, "out", "1000"),
            _leg(account, btc, "in", "0.04"),
            _leg(account, btc, "fee", "0.0001", charged_against=1),
        ],
    )

    assert _rows(client) == [
        '"Trade","0.0399","BTC","1000","EUR","0.0001","BTC","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{trade}-1","","",""'
    ]


def test_a_fee_in_a_third_asset_is_a_row_of_its_own(client, db):
    account = _account(db)
    eur, btc, bnb = _eur(db), _coin(db), _coin(db, "BNB", "bnb")
    trade = _record(
        db,
        "trade",
        [
            _leg(account, eur, "out", "1000"),
            _leg(account, btc, "in", "0.04"),
            _leg(account, bnb, "fee", "0.01", charged_against=1),
        ],
    )

    assert _rows(client) == [
        '"Trade","0.04","BTC","1000","EUR","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{trade}-1","","",""',
        '"Other Fee","","","0.01","BNB","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{trade}-2","","",""',
    ]


def test_a_withdrawal_states_its_network_fee(client, db):
    account = _account(db)
    btc = _coin(db)
    sent = _record(
        db,
        "transfer_out",
        [_leg(account, btc, "out", "0.5"), _leg(account, btc, "fee", "0.0002", charged_against=0)],
    )

    assert _rows(client) == [
        '"Withdrawal","","","0.5002","BTC","0.0002","BTC","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{sent}-1","","",""'
    ]


def test_a_security_is_left_out_and_said_so(client, db):
    """CoinTracking holds coins and currencies. A security's trade is not
    half-exported as cash leaving for nothing — it is named as left out."""
    account = _account(db, "Scalable", "broker", "Depot")
    with db.begin() as connection:
        connection.exec_driver_sql("UPDATE platform SET withholding = 'none'")
    eur = _eur(db)
    share = instruments.create_security(
        db, symbol="SAP", name="A share", type="share", isin="DE0007164600"
    )
    bought = _record(
        db, "trade", [_leg(account, eur, "out", "500"), _leg(account, share, "in", "3")]
    )

    assert _rows(client) == []
    assert _left_out(client) == [
        {
            "transaction_id": bought,
            "type": "trade",
            "occurred_at": "2031-03-14T12:30:05Z",
            "reason": "SAP is a security, and CoinTracking holds only coins and currencies.",
        }
    ]


@pytest.mark.parametrize("stance", ["ignored", "dangerous"])
def test_an_asset_outside_the_cost_basis_is_left_out_and_said_so(client, db, stance):
    account = _account(db)
    spam = _token(db, "FREE", "0x00000000000000000000000000000000000000aa")
    # A dangerous verdict is global; an ignored one is the Account's.
    settled = stances.classify(
        db, spam, stance=stance, account_id=account if stance == "ignored" else None
    )
    assert not isinstance(settled, stances.Refusal)
    arrived = _record(db, "transfer_in", [_leg(account, spam, "in", "1000000")])

    assert _rows(client) == []
    (left_out,) = _left_out(client)
    assert left_out["transaction_id"] == arrived
    assert left_out["reason"] == (
        f"FREE stands {stance} at Kraken - Main, outside the cost basis here as well."
    )


def test_a_symbol_two_instruments_share_is_left_out_rather_than_merged(client, db):
    """CoinTracking tells assets apart by symbol alone, so two Instruments
    under one symbol would arrive there as one holding."""
    account = _account(db)
    first = _token(db, "USDX", "0x00000000000000000000000000000000000000a1")
    second = _token(db, "USDX", "0x00000000000000000000000000000000000000a2")
    one = _record(db, "transfer_in", [_leg(account, first, "in", "10")])
    other = _record(db, "transfer_in", [_leg(account, second, "in", "20")], occurred_at=JUNE)

    assert _rows(client) == []
    assert [(row["transaction_id"], row["reason"]) for row in _left_out(client)] == [
        (one, "The symbol USDX names more than one Instrument in this ledger."),
        (other, "The symbol USDX names more than one Instrument in this ledger."),
    ]


def test_an_ignored_namesake_does_not_take_the_real_asset_with_it(client, db):
    account = _account(db)
    real = _token(db, "USDX", "0x00000000000000000000000000000000000000a1")
    fake = _token(db, "USDX", "0x00000000000000000000000000000000000000a2")
    stances.classify(db, fake, stance="ignored", account_id=account)
    kept = _record(db, "transfer_in", [_leg(account, real, "in", "10")])
    _record(db, "transfer_in", [_leg(account, fake, "in", "999")])

    assert _rows(client) == [
        '"Deposit","10","USDX","","","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{kept}-1","","",""'
    ]


def test_a_namesake_that_is_itself_left_out_takes_nothing_with_it(client, db):
    account = _account(db)
    eur, btc = _eur(db), _coin(db)
    real = _token(db, "USDX", "0x00000000000000000000000000000000000000a1")
    other = _token(db, "usdx", "0x00000000000000000000000000000000000000a2")
    kept = _record(db, "transfer_in", [_leg(account, real, "in", "10")])
    # A basket no row can state — so its namesake never reaches the tool.
    _record(
        db,
        "trade",
        [
            _leg(account, eur, "out", "5"),
            _leg(account, other, "in", "1"),
            _leg(account, btc, "in", "0.0001"),
        ],
        occurred_at=JUNE,
    )

    assert _rows(client) == [
        '"Deposit","10","USDX","","","","","Kraken - Main","","",'
        f'"14.03.2031 12:30:05","{kept}-1","","",""'
    ]


def test_symbols_differing_only_in_case_are_one_symbol_to_the_tool(client, db):
    account = _account(db)
    upper = _token(db, "USDX", "0x00000000000000000000000000000000000000a1")
    lower = _token(db, "usdx", "0x00000000000000000000000000000000000000a2")
    _record(db, "transfer_in", [_leg(account, upper, "in", "10")])
    _record(db, "transfer_in", [_leg(account, lower, "in", "20")], occurred_at=JUNE)

    assert _rows(client) == []
    assert len(_left_out(client)) == 2


def test_a_fee_no_row_can_state_is_a_row_of_its_own_where_it_was_charged(client, db):
    """A second fee, a fee charged at another Account, and a fee that would
    consume everything that arrived: none is folded, none is lost."""
    spot = _account(db)
    funding = _account(db, "Bitpanda")
    eur, btc = _eur(db), _coin(db)
    trade = _record(
        db,
        "trade",
        [
            _leg(spot, eur, "out", "1000"),
            _leg(spot, btc, "in", "0.04"),
            _leg(spot, eur, "fee", "2", charged_against=0),
            _leg(spot, eur, "fee", "1", charged_against=0),
            _leg(funding, eur, "fee", "0.50", charged_against=0),
            _leg(spot, btc, "fee", "0.04", charged_against=1),
        ],
    )

    tail = '"","",' + '"14.03.2031 12:30:05"'
    assert _rows(client) == [
        f'"Trade","0.04","BTC","1002","EUR","2","EUR","Kraken - Main",{tail},"{trade}-1","","",""',
        f'"Other Fee","","","1","EUR","","","Kraken - Main",{tail},"{trade}-2","","",""',
        f'"Other Fee","","","0.50","EUR","","","Bitpanda - Main",{tail},"{trade}-3","","",""',
        f'"Other Fee","","","0.04","BTC","","","Kraken - Main",{tail},"{trade}-4","","",""',
    ]


def test_an_unattached_fee_beside_several_rows_is_a_row_of_its_own(client, db):
    account = _account(db)
    btc, eth = _coin(db), _coin(db, "ETH", "ethereum")
    sent = _record(
        db,
        "transfer_out",
        [
            _leg(account, btc, "out", "1"),
            _leg(account, eth, "out", "2"),
            _leg(account, eth, "fee", "0.001"),
        ],
    )

    assert [row.split(",")[:5] for row in _rows(client)] == [
        ['"Withdrawal"', '""', '""', '"1"', '"BTC"'],
        ['"Withdrawal"', '""', '""', '"2"', '"ETH"'],
        ['"Other Fee"', '""', '""', '"0.001"', '"ETH"'],
    ]
    assert [row.split(",")[11] for row in _rows(client)] == [
        f'"{sent}-1"',
        f'"{sent}-2"',
        f'"{sent}-3"',
    ]


def test_a_name_holding_a_comma_or_a_quote_stays_one_field(client, db):
    account = _account(db, 'Bank "One", Ltd', "bank", "Giro")
    eur = _eur(db)
    _record(db, "interest", [_leg(account, eur, "in", "1.50")])

    (row,) = _rows(client)

    assert '"Bank ""One"", Ltd - Giro"' in row


def test_a_trade_cointracking_cannot_state_in_one_row_is_left_out(client, db):
    account = _account(db)
    eur, btc, eth = _eur(db), _coin(db), _coin(db, "ETH", "ethereum")
    basket = _record(
        db,
        "trade",
        [
            _leg(account, eur, "out", "1000"),
            _leg(account, btc, "in", "0.02"),
            _leg(account, eth, "in", "0.3"),
        ],
    )

    assert _rows(client) == []
    (left_out,) = _left_out(client)
    assert left_out["transaction_id"] == basket
    assert left_out["reason"] == (
        "A CoinTracking trade is one asset for one other at one place;"
        " this one records 2 arriving and 1 leaving."
    )


def test_a_trade_across_two_accounts_is_left_out(client, db):
    spot = _account(db)
    earn = _account(db, "Bitpanda")
    eur, btc = _eur(db), _coin(db)
    _record(db, "trade", [_leg(spot, eur, "out", "1000"), _leg(earn, btc, "in", "0.02")])

    assert _rows(client) == []
    (left_out,) = _left_out(client)
    assert left_out["reason"] == (
        "A CoinTracking trade is one asset for one other at one place;"
        " this one spans Kraken - Main and Bitpanda - Main."
    )


def test_the_summary_counts_the_rows_of_the_file(client, db):
    account = _account(db)
    eur, btc = _eur(db), _coin(db)
    _record(db, "trade", [_leg(account, eur, "out", "1000"), _leg(account, btc, "in", "0.02")])
    _record(db, "transfer_out", [_leg(account, btc, "out", "0.01")], occurred_at=JUNE)

    assert client.get(SUMMARY_URL).json() == {
        "format": "cointracking",
        "filename": "open-leprechaun-ledger-cointracking.csv",
        "row_count": 2,
        "left_out": [],
    }


def test_an_empty_ledger_exports_the_header_alone(client, db):
    assert _file(client).text == f"{HEADER}\n"
    assert client.get(SUMMARY_URL).json()["row_count"] == 0


def test_the_same_ledger_produces_the_same_file_oldest_first(client, db):
    account = _account(db)
    btc = _coin(db)
    # Recorded newest first, and two at one instant: neither the order rows
    # were written in nor a tie may decide the file.
    later = _record(db, "transfer_out", [_leg(account, btc, "out", "0.1")], occurred_at=JUNE)
    first = _record(db, "transfer_in", [_leg(account, btc, "in", "1")])
    second = _record(db, "staking_reward", [_leg(account, btc, "in", "0.001")])

    once, again = _file(client).content, _file(client).content

    assert once == again
    assert [row.split(",")[11] for row in _rows(client)] == [
        f'"{first}-1"',
        f'"{second}-1"',
        f'"{later}-1"',
    ]


def test_an_instant_is_stated_in_utc_whatever_offset_it_was_recorded_in(client, db):
    account = _account(db)
    btc = _coin(db)
    berlin_midnight = datetime.fromisoformat("2031-01-01T00:30:00+01:00")
    _record(db, "transfer_in", [_leg(account, btc, "in", "1")], occurred_at=berlin_midnight)

    (row,) = _rows(client)

    assert row.split(",")[10] == '"31.12.2030 23:30:00"'


def test_the_file_carries_no_more_than_the_tool_needs(client, db):
    """A note is the Admin's own words and an Account's reference is an
    address or IBAN: neither helps a second engine compute a year."""
    account = _account(db, external_reference="bc1qexamplereference", access_software="Sparrow")
    btc = _coin(db)
    created = transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=MARCH,
        note="a private remark",
        legs=[_leg(account, btc, "in", "1")],
    )
    assert isinstance(created, int)

    text = _file(client).text

    assert "a private remark" not in text
    assert "bc1qexamplereference" not in text
    assert "Sparrow" not in text
    assert "bitcoin" not in text


@pytest.mark.parametrize("url", [SUMMARY_URL, FILE_URL])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_data_flows_outward_only(client, db, url, method):
    assert getattr(client, method)(url).status_code == 405
