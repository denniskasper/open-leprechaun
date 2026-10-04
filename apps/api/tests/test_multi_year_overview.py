"""The multi-year overview (ticket 57): one row per Tax Year under each
regime — gross, offsets, allowance, taxable and tax — so carryforwards and
trends are read across years rather than dug out of individual reports.

The seam is the HTTP API over real Postgres, like the reports it sits beside:
the overview is what the engines state for every year at once, and a year
whose prerequisites are unfinished says so with the reason and the screen
that fixes it.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import (
    crypto_prices,
    instruments,
    platforms,
    stances,
    statutory,
    transactions,
)
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import futures, multi_year_overview
from open_leprechaun.services.statutory import KEYS

# Years no migration seeds, so every figure a test asserts rests on values
# the test itself configured.
BOUGHT_2031 = datetime(2031, 3, 14, 12, 0, tzinfo=UTC)
SOLD_2031 = datetime(2031, 6, 3, 12, 0, tzinfo=UTC)
LATER_2031 = datetime(2031, 9, 9, 12, 0, tzinfo=UTC)
SOLD_2032 = datetime(2032, 6, 3, 12, 0, tzinfo=UTC)
SOLD_2033 = datetime(2033, 6, 3, 12, 0, tzinfo=UTC)


class FakeReferenceRateSource:
    """The reference-rate port's fake: these ledgers settle in the numéraire
    or a euro stablecoin, so no rate is ever asked for."""

    def daily_rates(self, currency, start, end):
        return []


@pytest.fixture
def store(db):
    """The migrated database with this file's statutory years wiped —
    statutory rows outlive the shared `db` fixture, which resets only the
    ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


@pytest.fixture
def client(store):
    """The API bound to the migrated test database, rates through the fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: store
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


# What the tests' years are configured with unless a test says otherwise: a
# 1000 € Freigrenze on each personal-rate regime, a 1000 € allowance, the
# flat rate and the surcharge.
CONFIGURED = {
    "private_sale_exemption_limit": "1000",
    "other_income_exemption_limit": "256",
    "saver_allowance_single": "1000",
    "flat_rate": "0.25",
    "solidarity_surcharge_rate": "0.055",
}


def _configure(db, *years, **overrides):
    """A complete statutory year: every required key set, so no year is
    blocked over configuration unless a test leaves it out on purpose."""
    for year in years:
        for key, definition in KEYS.items():
            value = overrides.get(key, CONFIGURED.get(key, "0" if definition.required else None))
            if value is not None:
                statutory.upsert_value(
                    db, year=year, key=key, value=Decimal(value), source="a test value"
                )


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _btc(db, account):
    """A kept, priced coin — nothing about it blocks a year."""
    btc = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    settled = stances.classify(db, btc, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    crypto_prices.store_quote(
        db, instrument_id=btc, price_eur=Decimal("50000"), source="a test", as_of=SOLD_2031
    )
    return btc


def _trade(db, account, give, get, *, given, gotten, occurred_at):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=give, role="out", quantity=Decimal(given)),
            Leg(account_id=account, instrument_id=get, role="in", quantity=Decimal(gotten)),
        ],
    )
    assert isinstance(created, int)
    return created


def _eurc(db, account):
    """A kept euro stablecoin: its peg values it by identity, so an amount is
    its own EUR market value and no rate row is needed."""
    eurc = instruments.create_crypto_token(
        db,
        symbol="EURC",
        name="Euro Coin",
        chain="ethereum",
        contract_address="0x1abaea1f7c830bd89acc67ec4af516284b1bc33c",
        pegged_currency="EUR",
    )
    settled = stances.classify(db, eurc, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    return eurc


def _income(db, account, instrument, *, type, quantity, occurred_at=SOLD_2031):
    created = transactions.create_transaction(
        db,
        type=type,
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity))
        ],
    )
    assert isinstance(created, int)
    return created


def _futures_result(db, account, eur, *, realized, closed_at):
    """A closed euro-settled futures position: its result is one event in
    the Termingeschäfte pot, in the year it closed."""
    created = futures.record_manual_position(
        db,
        futures.FuturesPosition(
            account_id=account,
            symbol="BTC-PERP",
            side="long",
            quantity=Decimal("1"),
            settlement_instrument_id=eur,
            opened_at=closed_at.replace(month=1),
            closed_at=closed_at,
            realized=Decimal(realized),
            fees=Decimal("0"),
        ),
    )
    assert isinstance(created, int)
    return created


def _pots(year):
    return {pot["category"]: pot for pot in year["capital_income"]["categories"]}


def _layers(layers):
    return [
        (layer["origin_year"], Decimal(layer["amount_eur"]), layer["opening"]) for layer in layers
    ]


def _years(client):
    answered = client.get("/api/multi-year-overview")
    assert answered.status_code == 200, answered.text
    return {row["year"]: row for row in answered.json()["years"]}


FIGURES = (
    "gross_eur",
    "offsets_eur",
    "allowance_limit_eur",
    "allowance_eur",
    "taxable_eur",
    "tax_eur",
)


def _figures(regime):
    """A regime row's columns as exact decimals — each crosses the API as a
    fixed-point string, whose trailing zeros say nothing about the amount."""
    return {name: Decimal(regime[name]) if regime[name] is not None else None for name in FIGURES}


# --- Private sales (§23) ------------------------------------------------------


def test_a_private_sale_year_states_gross_offsets_allowance_and_taxable(store, client):
    """One row per year under the private-sale regime: a 2000 € gain over
    the 1000 € Freigrenze is taxable whole — the limit frees nothing once it
    is reached — and no euro of tax is stated, the rate being personal
    (ADR-0007)."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    btc = _btc(store, account)
    _trade(store, account, eur, btc, given="10000", gotten="1", occurred_at=BOUGHT_2031)
    _trade(store, account, btc, eur, given="1", gotten="12000", occurred_at=SOLD_2031)

    year = _years(client)[2031]

    assert year["blockers"] == []
    assert _figures(year["private_sales"]) == {
        "gross_eur": Decimal("2000"),
        "offsets_eur": Decimal("0"),
        "allowance_limit_eur": Decimal("1000"),
        "allowance_eur": Decimal("0"),
        "taxable_eur": Decimal("2000"),
        "tax_eur": None,
    }


def test_a_loss_is_an_offset_and_the_freigrenze_frees_the_whole_remainder(store, client):
    """§23 Abs. 3 Satz 5 EStG read across the columns: a 1500 € gain and a
    700 € loss leave 800 €, under the 1000 € Freigrenze — so the whole 800 €
    is freed and nothing is taxable."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    btc = _btc(store, account)
    _trade(store, account, eur, btc, given="20000", gotten="2", occurred_at=BOUGHT_2031)
    _trade(store, account, btc, eur, given="1", gotten="11500", occurred_at=SOLD_2031)
    _trade(store, account, btc, eur, given="1", gotten="9300", occurred_at=LATER_2031)

    private_sales = _figures(_years(client)[2031]["private_sales"])

    assert private_sales["gross_eur"] == Decimal("1500")
    assert private_sales["offsets_eur"] == Decimal("700")
    assert private_sales["allowance_eur"] == Decimal("800")
    assert private_sales["taxable_eur"] == Decimal("0")


def test_a_losing_private_sale_year_states_its_losses_in_full(store, client):
    """A year that lost more than it gained owes nothing — and says by how
    much it lost, rather than trimming the offsets to the gains they met."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    btc = _btc(store, account)
    _trade(store, account, eur, btc, given="20000", gotten="2", occurred_at=BOUGHT_2031)
    _trade(store, account, btc, eur, given="1", gotten="10500", occurred_at=SOLD_2031)
    _trade(store, account, btc, eur, given="1", gotten="8800", occurred_at=LATER_2031)

    private_sales = _figures(_years(client)[2031]["private_sales"])

    assert private_sales["gross_eur"] == Decimal("500")
    assert private_sales["offsets_eur"] == Decimal("1200")
    assert private_sales["allowance_eur"] == Decimal("0")
    assert private_sales["taxable_eur"] == Decimal("0")


# --- Other income (§22 Nr. 3) -------------------------------------------------


def test_an_other_income_year_states_its_pooled_income_and_what_is_taxable(store, client):
    """§22 Nr. 3 Satz 2 EStG as a row: 300 € of staking rewards reach the
    256 € Freigrenze, so the whole amount is taxable — nothing offsets
    income, the limit frees nothing, and no euro of tax is stated."""
    _configure(store, 2031)
    account = _account(store)
    _income(store, account, _eurc(store, account), type="staking_reward", quantity="300")

    assert _figures(_years(client)[2031]["other_income"]) == {
        "gross_eur": Decimal("300"),
        "offsets_eur": Decimal("0"),
        "allowance_limit_eur": Decimal("256"),
        "allowance_eur": Decimal("0"),
        "taxable_eur": Decimal("300"),
        "tax_eur": None,
    }


# --- Capital income (§20) -----------------------------------------------------


def test_a_capital_income_year_states_the_allowance_applied_and_the_tax_owed(store, client):
    """§20 Abs. 9 und §32d Abs. 1 EStG as a row: a 1500 € dividend less the
    1000 € Sparerpauschbetrag leaves 500 € taxable — and here the rate is
    statutory, so the tax is stated: 125 € plus 5.5 % surcharge, 131.88 €."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="1500")

    assert _figures(_years(client)[2031]["capital_income"]) == {
        "gross_eur": Decimal("1500"),
        "offsets_eur": Decimal("0"),
        "allowance_limit_eur": Decimal("1000"),
        "allowance_eur": Decimal("1000"),
        "taxable_eur": Decimal("500"),
        "tax_eur": Decimal("131.88"),
    }


def test_a_loss_year_produces_a_carryforward_and_the_year_consuming_it_names_its_origin(
    store, client
):
    """§20 Abs. 6 Satz 2 und 3 EStG across the rows: a 400 € futures loss in
    2031 carries out of its pot, and 2032's 1000 € gain consumes it — the
    row naming 2031 as where it came from — before the allowance applies."""
    _configure(store, 2031, 2032)
    account, eur = _account(store), _eur(store)
    _futures_result(store, account, eur, realized="-400", closed_at=SOLD_2031)
    _futures_result(store, account, eur, realized="1000", closed_at=SOLD_2032)

    years = _years(client)

    produced = _pots(years[2031])["termingeschaefte"]
    assert Decimal(produced["produced_eur"]) == Decimal("400")
    assert _layers(produced["carryforward_in"]) == []
    assert _layers(produced["carryforward_out"]) == [(2031, Decimal("400"), False)]
    consumed = _pots(years[2032])["termingeschaefte"]
    assert _layers(consumed["carryforward_in"]) == [(2031, Decimal("400"), False)]
    assert _layers(consumed["consumed"]) == [(2031, Decimal("400"), False)]
    assert _layers(consumed["carryforward_out"]) == []
    assert Decimal(produced["carryforward_out_eur"]) == Decimal("400")
    assert Decimal(consumed["carryforward_in_eur"]) == Decimal("400")
    assert Decimal(consumed["consumed_eur"]) == Decimal("400")
    assert Decimal(consumed["carryforward_out_eur"]) == Decimal("0")
    assert _figures(years[2032]["capital_income"]) == {
        "gross_eur": Decimal("1000"),
        "offsets_eur": Decimal("400"),
        "allowance_limit_eur": Decimal("1000"),
        "allowance_eur": Decimal("600"),
        "taxable_eur": Decimal("0"),
        "tax_eur": Decimal("0"),
    }


def test_a_carryforward_stays_in_its_own_pot_across_the_years(store, client):
    """§20 Abs. 6 EStG: the 2031 futures loss shelters nothing in 2032's
    general pot — it walks through the year untouched, in and out of the
    pot it was made in."""
    _configure(store, 2031, 2032)
    account, eur = _account(store), _eur(store)
    _futures_result(store, account, eur, realized="-400", closed_at=SOLD_2031)
    _income(store, account, eur, type="dividend", quantity="1500", occurred_at=SOLD_2032)

    pots = _pots(_years(client)[2032])

    assert _layers(pots["termingeschaefte"]["carryforward_out"]) == [(2031, Decimal("400"), False)]
    assert _layers(pots["sonstige"]["consumed"]) == []


def test_an_opening_carryforward_from_an_earlier_assessment_is_shown_as_such(store, client):
    """ADR-0013: a 300 € balance entered for 2030 from an assessment
    predating the ledger opens that year's row — before the ledger's first
    Transaction — marked as an opening balance, and stays so marked when
    2031's dividend consumes it."""
    _configure(store, 2030, 2031)
    statutory.upsert_value(
        store,
        year=2030,
        key="opening_carryforward_sonstige",
        value=Decimal("300"),
        source="Verlustfeststellungsbescheid",
    )
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="500")

    years = _years(client)

    assert _layers(_pots(years[2030])["sonstige"]["carryforward_in"]) == [
        (2030, Decimal("300"), True)
    ]
    assert _layers(_pots(years[2031])["sonstige"]["consumed"]) == [(2030, Decimal("300"), True)]
    assert _figures(years[2031]["capital_income"])["offsets_eur"] == Decimal("300")


# --- Blocked years ------------------------------------------------------------


def test_a_year_missing_its_statutory_values_is_blocked_with_the_reason_and_its_fix(store, client):
    """A year with unfinished prerequisites states no figure it cannot
    stand behind: 2032 has no statutory configuration, so every regime is
    unstated and the one blocker names the gap and the screen that closes
    it — while 2031 beside it answers untouched."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="1500")
    _income(store, account, eur, type="dividend", quantity="1500", occurred_at=SOLD_2032)

    years = _years(client)

    assert years[2031]["blockers"] == []
    assert years[2031]["capital_income"] is not None
    blocked = years[2032]
    assert (blocked["private_sales"], blocked["other_income"], blocked["capital_income"]) == (
        None,
        None,
        None,
    )
    (blocker,) = blocked["blockers"]
    assert blocker["kind"] == "missing_statutory_configuration"
    assert "2032" in blocker["detail"]
    assert blocker["resolve_path"] == "/settings/statutory"


def test_a_blocked_year_still_states_the_figures_its_engines_can(store, client):
    """An unmatched transfer leaves the year unfit to finalise, and the row
    says so with the screen that settles it — but the engines can still
    state the year as the ledger stands, exactly as a draft report would."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    btc = _btc(store, account)
    _trade(store, account, eur, btc, given="20000", gotten="2", occurred_at=BOUGHT_2031)
    _trade(store, account, btc, eur, given="1", gotten="12000", occurred_at=SOLD_2031)
    created = transactions.create_transaction(
        store,
        type="transfer_out",
        occurred_at=LATER_2031,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("1"))],
    )
    assert isinstance(created, int)

    year = _years(client)[2031]

    (blocker,) = year["blockers"]
    assert (blocker["kind"], blocker["resolve_path"]) == ("unmatched_transfers", "/transfers")
    assert _figures(year["private_sales"])["taxable_eur"] == Decimal("2000")


def test_a_blocker_withholds_only_the_regime_it_stands_in_the_way_of(store, client):
    """A sale of coins the ledger never saw arrive blocks the year and
    leaves the private-sale row unstated — but capital income rests on
    nothing that is missing, and still answers."""
    _configure(store, 2031)
    account, eur = _account(store), _eur(store)
    btc = _btc(store, account)
    _trade(store, account, btc, eur, given="1", gotten="12000", occurred_at=SOLD_2031)
    _income(store, account, eur, type="dividend", quantity="1500", occurred_at=LATER_2031)

    year = _years(client)[2031]

    assert year["private_sales"] is None
    assert [blocker["kind"] for blocker in year["blockers"]] == ["lot_shortfalls"]
    assert year["blockers"][0]["resolve_path"] == "/transactions"
    assert _figures(year["capital_income"])["taxable_eur"] == Decimal("500")


def test_a_regime_awaiting_a_valuation_is_blocked_rather_than_stated_as_zero(store, client):
    """A staking reward in a coin with no price for its day has no market
    value yet (ADR-0024): the other-income row is unstated — never a zero —
    and the year says what it waits on, though no pre-flight check does."""
    _configure(store, 2031)
    account = _account(store)
    _income(
        store,
        account,
        _btc(store, account),
        type="staking_reward",
        quantity="0.01",
        occurred_at=LATER_2031,
    )

    year = _years(client)[2031]

    assert year["other_income"] is None
    (blocker,) = year["blockers"]
    assert blocker["kind"] == "awaiting_valuation"
    assert blocker["count"] == 1
    assert blocker["resolve_path"] == "/instruments"


def test_an_awaited_valuation_is_named_beside_another_instrument_never_priced(store, client):
    """Two different gaps, two reasons: one coin was never priced at all,
    another has a price but none for the day its reward arrived. Neither
    reason stands in for the other."""
    _configure(store, 2031)
    account = _account(store)
    sol = instruments.create_native_coin(store, symbol="SOL", name="Solana", chain="solana")
    settled = stances.classify(store, sol, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    _income(store, account, sol, type="staking_reward", quantity="1")
    _income(
        store,
        account,
        _btc(store, account),
        type="staking_reward",
        quantity="0.01",
        occurred_at=LATER_2031,
    )

    kinds = {blocker["kind"] for blocker in _years(client)[2031]["blockers"]}

    assert {"unpriced_instruments", "awaiting_valuation"} <= kinds


# --- Which years ----------------------------------------------------------------


def test_every_year_between_the_first_and_the_last_has_a_row(store, client):
    """A year the ledger never touched still carries what came before it:
    2032 has no Transaction and a row all the same, between 2031 and 2033."""
    _configure(store, 2031, 2032, 2033)
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="1500")
    _income(store, account, eur, type="dividend", quantity="1500", occurred_at=SOLD_2033)

    years = _years(client)

    assert sorted(years) == [2031, 2032, 2033]
    assert _figures(years[2032]["capital_income"])["gross_eur"] == Decimal("0")


def test_the_overview_runs_through_the_current_year(store):
    """The current Tax Year is still accruing — a carryforward walks into it
    and a Vorabpauschale falls due in it — so the rows run on to today even
    where the ledger's last Transaction is years back."""
    _configure(store, 2031, 2032, 2033)
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="1500")

    years = multi_year_overview.overview(store, FakeReferenceRateSource(), today=date(2033, 2, 1))

    assert [year.year for year in years] == [2031, 2032, 2033]


def test_an_empty_ledger_has_no_years(store, client):
    assert client.get("/api/multi-year-overview").json() == {"years": []}
