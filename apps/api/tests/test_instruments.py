"""Instrument identity, per ADR-0010: tokens key on chain and contract,
native coins on symbol, securities on ISIN with an identifier history, and a
Listing is its own concept for price sources to point at.

The seams are the repository over real Postgres — the rules under test are the
schema's own constraints — and the HTTP endpoint through the app.
"""

from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments
from open_leprechaun.seed import seed

UNISWAP_CONTRACT = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"
IMPOSTOR_CONTRACT = "0xb5c578947de0fd71303f71f2c3d41767438bd0de"


def test_two_tokens_sharing_a_symbol_coexist(db):
    """The v1 failure mode: same ticker, different token. Two rows, always."""
    uniswap = instruments.create_crypto_token(
        db, symbol="UNI", name="Uniswap", chain="ethereum", contract_address=UNISWAP_CONTRACT
    )
    impostor = instruments.create_crypto_token(
        db, symbol="UNI", name="Unicorn Farm", chain="bsc", contract_address=IMPOSTOR_CONTRACT
    )

    assert uniswap is not None
    assert impostor is not None
    assert uniswap != impostor


def test_the_same_contract_is_one_identity_regardless_of_checksum_casing(db):
    first = instruments.create_crypto_token(
        db, symbol="UNI", name="Uniswap", chain="ethereum", contract_address=UNISWAP_CONTRACT
    )
    duplicate = instruments.create_crypto_token(
        db,
        symbol="UNI-2",
        name="Uniswap again",
        chain="ethereum",
        contract_address=UNISWAP_CONTRACT.upper().replace("0X", "0x"),
    )

    assert first is not None
    assert duplicate is None


def test_a_native_coin_keys_on_its_symbol(db):
    first = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    duplicate = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin?", chain="bitcoin")

    assert first is not None
    assert duplicate is None


def test_a_native_coin_and_a_token_sharing_a_symbol_coexist(db):
    """Symbol is identity only within the native-coin family slice, never across."""
    native = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    token = instruments.create_crypto_token(
        db, symbol="ETH", name="Fake Ether", chain="bsc", contract_address=IMPOSTOR_CONTRACT
    )

    assert native is not None
    assert token is not None


def test_a_security_keys_on_its_isin(db):
    first = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )
    duplicate = instruments.create_security(
        db, symbol="IWDA", name="Same fund, other ticker", type="etf", isin="IE00B4L5Y983"
    )

    assert first is not None
    assert duplicate is None


def test_the_three_families_coexist_under_one_concept(db):
    """One table answers for crypto, security and cash alike."""
    crypto = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    security = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )
    cash = instruments.create_cash(db, symbol="EUR", name="Euro")

    families = {row.family for row in instruments.list_instruments(db)}
    assert None not in (crypto, security, cash)
    assert families == {"crypto", "security", "cash"}


def test_a_listing_names_venue_and_quote_currency_and_is_unique_per_pair(db):
    """The same ISIN trades on several venues in several currencies; each pair
    is one Listing, and repeating a pair does not mint a second."""
    fund = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )

    xetra = instruments.add_listing(db, fund, venue="XETRA", quote_currency="EUR")
    london = instruments.add_listing(db, fund, venue="LSE", quote_currency="USD")
    repeat = instruments.add_listing(db, fund, venue="XETRA", quote_currency="EUR")

    assert xetra is not None
    assert london is not None
    assert repeat is None


def test_an_isin_change_orphans_nothing(db):
    """A merger reassigns the ISIN; the row, its listings and a lookup by the
    superseded identifier all still reach the same Instrument."""
    fund = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )
    listing = instruments.add_listing(db, fund, venue="XETRA", quote_currency="EUR")

    assert instruments.change_isin(db, fund, new_isin="IE000TESTNEW1") is True

    by_old = instruments.find_by_identifier(db, "IE00B4L5Y983")
    by_new = instruments.find_by_identifier(db, "IE000TESTNEW1")
    assert [row.id for row in by_old] == [fund]
    assert [row.id for row in by_new] == [fund]
    assert [row.id for row in instruments.list_listings(db)] == [listing]


def test_a_changed_isin_cannot_collide_with_another_instrument(db):
    fund = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )
    other = instruments.create_security(
        db, symbol="VWCE", name="Vanguard FTSE All-World", type="etf", isin="IE00BK5BQT80"
    )

    assert instruments.change_isin(db, fund, new_isin="IE00BK5BQT80") is False
    assert {row.isin for row in instruments.list_instruments(db)} == {
        "IE00B4L5Y983",
        "IE00BK5BQT80",
    }
    assert other is not None


def test_the_schema_itself_refuses_a_checksum_cased_duplicate_contract(db):
    """Identity is the index's job, not a courtesy of the repository: a write
    path that skips the lowercasing still cannot mint a second identity."""
    instruments.create_crypto_token(
        db, symbol="UNI", name="Uniswap", chain="ethereum", contract_address=UNISWAP_CONTRACT
    )

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, chain, contract_address)"
                " VALUES ('crypto', 'token', 'UNI', 'Uniswap again', 'ethereum', :address)"
            ),
            {"address": UNISWAP_CONTRACT.upper().replace("0X", "0x")},
        )


def test_every_family_of_instrument_keeps_an_identifier_history(db):
    """The ticket says each Instrument, not each security: a token's contract
    and a native coin's symbol are on record from birth, so a later identifier
    change has something to supersede rather than nothing to point at."""
    token = instruments.create_crypto_token(
        db, symbol="UNI", name="Uniswap", chain="ethereum", contract_address=UNISWAP_CONTRACT
    )
    native = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")

    assert [row.id for row in instruments.find_by_identifier(db, UNISWAP_CONTRACT)] == [token]
    assert [row.id for row in instruments.find_by_identifier(db, "BTC")] == [native]


def test_an_alias_may_only_be_a_wkn_or_a_ticker(db):
    """The current ISIN moves through change_isin, never through the alias
    door — otherwise history and the identity column could disagree."""
    fund = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )

    with pytest.raises(ValueError, match="isin"):
        instruments.add_identifier(db, fund, kind="isin", value="IE000TESTNEW1")


def test_an_alias_is_a_hint_that_may_name_several_candidates(db):
    """WKN and ticker are lookup aliases, never identity: resolution may answer
    "I don't know which of these you mean" by returning more than one."""
    fund = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )
    other = instruments.create_security(
        db, symbol="VWCE", name="Vanguard FTSE All-World", type="etf", isin="IE00BK5BQT80"
    )
    instruments.add_identifier(db, fund, kind="ticker", value="SWDA")
    instruments.add_identifier(db, other, kind="ticker", value="SWDA")

    candidates = instruments.find_by_identifier(db, "SWDA")

    assert {row.id for row in candidates} == {fund, other}


def test_the_api_lists_instruments_with_identity_and_listings(client, db):
    """One endpoint feeds the UI everything it needs to tell two same-symbol
    rows apart: family, type and the family's identifying attributes."""
    instruments.create_crypto_token(
        db, symbol="UNI", name="Uniswap", chain="ethereum", contract_address=UNISWAP_CONTRACT
    )
    instruments.create_crypto_token(
        db, symbol="UNI", name="Unicorn Farm", chain="bsc", contract_address=IMPOSTOR_CONTRACT
    )
    fund = instruments.create_security(
        db, symbol="EUNL", name="iShares Core MSCI World", type="etf", isin="IE00B4L5Y983"
    )
    instruments.add_listing(db, fund, venue="XETRA", quote_currency="EUR")

    response = client.get("/api/instruments")

    assert response.status_code == 200
    by_name = {row["name"]: row for row in response.json()}
    assert by_name["Uniswap"]["chain"] == "ethereum"
    assert by_name["Uniswap"]["contract_address"] == UNISWAP_CONTRACT
    assert by_name["Unicorn Farm"]["chain"] == "bsc"
    assert by_name["Unicorn Farm"]["contract_address"] == IMPOSTOR_CONTRACT
    assert by_name["iShares Core MSCI World"]["isin"] == "IE00B4L5Y983"
    (listing,) = by_name["iShares Core MSCI World"]["listings"]
    assert listing["venue"] == "XETRA"
    assert listing["quote_currency"] == "EUR"
    # A bare security's first Listing takes the price source (ticket 45).
    assert listing["price_source"] is True


def test_the_seed_demonstrates_a_shared_symbol(db):
    """The development database carries the v1 collision case, so the UI has
    two same-symbol rows to tell apart from day one."""
    seed(db)

    symbols = Counter(row.symbol for row in instruments.list_instruments(db))
    assert max(symbols.values()) >= 2
