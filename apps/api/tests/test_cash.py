"""Cash Instruments and the EUR numéraire, per ADR-0011: cash is an Instrument
like any other, EUR is the numéraire whose movement is not a disposal, and the
numéraire is configuration — a flag the schema holds to at most one row — never
a symbol comparison in logic.

The seams are the repository over real Postgres — the rules under test are the
schema's own constraints — and the migration chain, which every environment
runs, so EUR exists wherever the schema does.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments
from open_leprechaun.seed import seed
from open_leprechaun.services.instruments import movement_is_disposal


def test_a_cash_instrument_opens_its_identifier_history_at_birth(db):
    """Like every family: the currency code is cash's identity, so it is also
    the identifier a later change would supersede."""
    dollar = instruments.create_cash(db, symbol="USD", name="US Dollar")

    assert [row.id for row in instruments.find_by_identifier(db, "USD")] == [dollar]


def test_the_schema_itself_admits_at_most_one_numeraire(db):
    """One numéraire is the index's job, not a courtesy of any write path: a
    second flagged row is refused however it arrives."""
    instruments.create_cash(db, symbol="EUR", name="Euro")
    with db.begin() as connection:
        connection.execute(text("UPDATE instrument SET is_numeraire = true WHERE symbol = 'EUR'"))

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, is_numeraire)"
                " VALUES ('cash', 'fiat', 'USD', 'US Dollar', true)"
            )
        )


def test_the_schema_refuses_a_numeraire_outside_the_cash_family(db):
    """The numéraire is a property of a currency, so nothing but cash can be
    flagged — a crypto or security row wearing the flag is a schema violation."""
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, chain, is_numeraire)"
                " VALUES ('crypto', 'native', 'BTC', 'Bitcoin', 'bitcoin', true)"
            )
        )


def test_a_cash_instrument_keys_on_its_currency_code(db):
    first = instruments.create_cash(db, symbol="USD", name="US Dollar")
    duplicate = instruments.create_cash(db, symbol="USD", name="Dollar again")

    assert first is not None
    assert duplicate is None


def test_the_numeraire_is_configuration_that_can_name_another_currency(db):
    """Nothing in logic says EUR: designating another cash Instrument moves the
    flag in one transaction, and the previous numéraire becomes ordinary."""
    euro = instruments.create_cash(db, symbol="EUR", name="Euro")
    franc = instruments.create_cash(db, symbol="CHF", name="Swiss Franc")

    assert instruments.designate_numeraire(db, euro) is True
    assert instruments.numeraire(db).id == euro

    assert instruments.designate_numeraire(db, franc) is True
    assert instruments.numeraire(db).id == franc
    assert instruments.numeraire(db).symbol == "CHF"


def test_only_cash_can_be_designated_the_numeraire(db):
    bitcoin = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")

    assert instruments.designate_numeraire(db, bitcoin) is False
    assert instruments.numeraire(db) is None


def test_moving_the_numeraire_is_not_a_disposal_and_moving_anything_else_is(db):
    """The rule the tax tickets will read: spending EUR creates no taxable
    event, while a non-EUR currency is an ordinary asset — the answer comes
    from the flag, so nothing anywhere compares a symbol to 'EUR'."""
    euro = instruments.create_cash(db, symbol="EUR", name="Euro")
    instruments.create_cash(db, symbol="USD", name="US Dollar")
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    instruments.designate_numeraire(db, euro)

    by_symbol = {row.symbol: row for row in instruments.list_instruments(db)}

    assert movement_is_disposal(by_symbol["EUR"]) is False
    assert movement_is_disposal(by_symbol["USD"]) is True
    assert movement_is_disposal(by_symbol["BTC"]) is True


def test_the_api_says_which_instrument_is_the_numeraire(client, db):
    """The UI needs one flag to mark the row — cash otherwise looks like any
    other Instrument, which is the point."""
    euro = instruments.create_cash(db, symbol="EUR", name="Euro")
    instruments.create_cash(db, symbol="USD", name="US Dollar")
    instruments.designate_numeraire(db, euro)

    response = client.get("/api/instruments")

    assert response.status_code == 200
    by_symbol = {row["symbol"]: row for row in response.json()}
    assert by_symbol["EUR"]["is_numeraire"] is True
    assert by_symbol["USD"]["is_numeraire"] is False


def test_a_fresh_database_is_born_with_eur_as_the_numeraire(fresh_db):
    """EUR arrives with the migration, not the seed: production needs the
    numéraire before the first transaction, and the seed never runs there."""
    numeraire = instruments.numeraire(fresh_db)

    assert numeraire is not None
    assert (numeraire.family, numeraire.type, numeraire.symbol) == ("cash", "fiat", "EUR")
    assert [row.id for row in instruments.find_by_identifier(fresh_db, "EUR")] == [numeraire.id]


def test_the_seed_holds_a_non_eur_currency_as_an_ordinary_asset(fresh_db):
    """The development database demonstrates the distinction from day one: EUR
    stays the numéraire, and a dollar balance is just another holding whose
    movement disposes of it."""
    seed(fresh_db)

    by_symbol = {row.symbol: row for row in instruments.list_instruments(fresh_db)}
    dollar = by_symbol["USD"]
    assert (dollar.family, dollar.type) == ("cash", "fiat")
    assert movement_is_disposal(dollar) is True
    assert [row.id for row in instruments.find_by_identifier(fresh_db, "USD")] == [dollar.id]
    assert instruments.numeraire(fresh_db).symbol == "EUR"
