"""Adding a coin, token or currency by hand: a venue's sync states a symbol
alone and so can resolve an Instrument but never create one — the Admin
states the identity once (ADR-0010), and every later sync resolves it."""

from sqlalchemy import text

USDC = {
    "kind": "token",
    "symbol": "USDC",
    "name": "USD Coin",
    "chain": "Ethereum",
    "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "pegged_currency": "USD",
}


def _listed(client, instrument_id):
    (found,) = [
        entry for entry in client.get("/api/instruments").json() if entry["id"] == instrument_id
    ]
    return found


def test_a_token_is_added_keyed_on_its_lowercased_chain_and_contract(db, client):
    response = client.post("/api/instruments", json=USDC)

    assert response.status_code == 201
    added = _listed(client, response.json()["id"])
    assert (added["family"], added["type"], added["symbol"]) == ("crypto", "token", "USDC")
    assert added["chain"] == "ethereum"
    assert added["contract_address"] == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    with db.connect() as connection:
        peg = connection.execute(
            text("SELECT pegged_currency FROM instrument WHERE id = :id"), {"id": added["id"]}
        ).scalar_one()
    assert peg == "USD"


def test_a_native_coin_is_added_with_its_chain_and_no_contract(db, client):
    response = client.post(
        "/api/instruments",
        json={"kind": "native", "symbol": "BTC", "name": "Bitcoin", "chain": " Bitcoin "},
    )

    assert response.status_code == 201
    added = _listed(client, response.json()["id"])
    assert (added["type"], added["chain"], added["contract_address"]) == (
        "native",
        "bitcoin",
        None,
    )


def test_a_currency_is_added_by_its_code(db, client):
    response = client.post(
        "/api/instruments", json={"kind": "cash", "symbol": "usd", "name": "US Dollar"}
    )

    assert response.status_code == 201
    added = _listed(client, response.json()["id"])
    assert (added["family"], added["type"], added["symbol"]) == ("cash", "fiat", "USD")


def test_an_identity_that_exists_is_refused_naming_the_instrument(db, client):
    assert client.post("/api/instruments", json=USDC).status_code == 201

    # Checksum casing and the chain's casing mint no second identity.
    again = client.post(
        "/api/instruments",
        json={**USDC, "symbol": "USDC2", "name": "Another", "chain": "ETHEREUM"},
    )

    assert again.status_code == 409
    assert "USD Coin" in again.json()["detail"]
    assert [e["symbol"] for e in client.get("/api/instruments").json()].count("USDC2") == 0


def test_a_native_coin_or_currency_that_exists_is_refused(db, client):
    bitcoin = {"kind": "native", "symbol": "BTC", "name": "Bitcoin", "chain": "bitcoin"}
    assert client.post("/api/instruments", json=bitcoin).status_code == 201

    assert client.post("/api/instruments", json=bitcoin).status_code == 409
    franc = {"kind": "cash", "symbol": "CHF", "name": "Swiss franc"}
    assert client.post("/api/instruments", json=franc).status_code == 201
    again = client.post("/api/instruments", json={**franc, "symbol": "chf", "name": "Franken"})
    assert again.status_code == 409
    assert "Swiss franc" in again.json()["detail"]


def test_a_symbol_another_instrument_wears_is_no_obstacle(db, client):
    """A symbol is a label, never a key (ADR-0010): the same coin on a second
    chain is a second Instrument."""
    assert client.post("/api/instruments", json=USDC).status_code == 201

    on_solana = client.post(
        "/api/instruments",
        json={
            **USDC,
            "chain": "solana",
            "contract_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        },
    )

    assert on_solana.status_code == 201
    # A base58 address means its casing and is stored as given.
    assert (
        _listed(client, on_solana.json()["id"])["contract_address"]
        == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    )


def test_a_malformed_hex_address_is_refused(db, client):
    for address in ("0xA0b8", "0x" + "g" * 40, "   "):
        response = client.post("/api/instruments", json={**USDC, "contract_address": address})
        assert response.status_code == 422, address


def test_a_peg_or_a_currency_code_is_three_letters(db, client):
    spelled_out = client.post("/api/instruments", json={**USDC, "pegged_currency": "dollar"})
    assert spelled_out.status_code == 422
    assert (
        client.post(
            "/api/instruments", json={"kind": "cash", "symbol": "DOLLAR", "name": "Dollar"}
        ).status_code
        == 422
    )


def test_a_blank_symbol_name_or_chain_is_refused(db, client):
    for field in ("symbol", "name", "chain"):
        response = client.post("/api/instruments", json={**USDC, field: "  "})
        assert response.status_code == 422, field
