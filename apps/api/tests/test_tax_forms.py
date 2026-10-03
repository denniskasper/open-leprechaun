"""Report sections shaped like the tax forms (ticket 51): the year's figures
laid out the way Anlage SO, Anlage KAP and Anlage KAP-INV are, each figure
naming the form line it belongs on where that is unambiguous and saying so
plainly where it is not — frozen with the report, restated by both exports.

The seam is the HTTP API over real Postgres — the sections are part of a
generated report and of its appendix downloads — with rates through the
reference-rate port's fake. The expected line numbers and printed labels are
the official forms' own, read per year (docs/research/tax-form-lines.md);
every amount is invented for the scenario and derives from no account.
"""

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import capital_income as capital_income_repository
from open_leprechaun.repositories import (
    instruments,
    platforms,
    stances,
    transactions,
)
from open_leprechaun.repositories.transactions import CapitalIncome, Leg


class FakeReferenceRateSource:
    """The reference-rate port's fake: whatever rates the test hands it,
    answered per query window."""

    def __init__(self, rates=()):
        self.rates = list(rates)

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


@pytest.fixture
def client(db):
    """The API bound to the migrated test database, rates through the fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


def _at(year, month=6, day=3):
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


def _account(db, platform_name="Kraken", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind="exchange")
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _kept_coin(db, account, symbol="BTC", chain="bitcoin"):
    coin = instruments.create_native_coin(db, symbol=symbol, name=symbol, chain=chain)
    settled = stances.classify(db, coin, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    return coin


def _transaction(db, type, occurred_at, legs, **declarations):
    created = transactions.create_transaction(
        db, type=type, occurred_at=occurred_at, note=None, legs=legs, **declarations
    )
    assert isinstance(created, int)
    return created


def _staking_reward(db, account, eur, *, amount, occurred_at):
    """A §22 receipt paid in the numéraire, so its market value is its
    quantity and no price is needed."""
    return _transaction(
        db,
        "staking_reward",
        occurred_at,
        [Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal(amount))],
    )


def _forms(client, *, year):
    generated = client.post("/api/reports", json={"year": year})
    assert generated.status_code == 201, generated.text
    report = client.get(f"/api/reports/{generated.json()['id']}").json()
    return report["figures"]["forms"]


def _section(forms, key):
    (section,) = [section for section in forms["sections"] if section["key"] == key]
    return section


def _line(section, key):
    (line,) = [line for line in section["lines"] if line["key"] == key]
    return line


# --- Anlage SO: Leistungen (§22 Nr. 3 EStG) ----------------------------------


def test_other_income_names_its_line_on_the_year_s_anlage_so(db, client):
    """The 2025 Anlage SO takes crypto-related Leistungen on Zeile 15 — the
    year's §22 income stands under that line with its printed label."""
    account, eur = _account(db), _eur(db)
    _staking_reward(db, account, eur, amount="300", occurred_at=_at(2025))

    forms = _forms(client, year=2025)

    leistungen = _section(forms, "so.leistungen")
    assert leistungen["form"] == "Anlage SO"
    income = _line(leistungen, "so.leistungen.einnahmen_krypto")
    assert income["form_lines"] == ["15"]
    assert income["label"] == "Einnahmen im Zusammenhang mit Kryptowerten:"
    assert income["mapping"] == "unambiguous"
    assert Decimal(income["amount_eur"]) == Decimal("300")


def test_the_line_number_follows_the_form_of_the_report_s_own_year(db, client):
    """Line numbers move between years: the 2024 Anlage SO takes the same
    figure on Zeile 11, under the label that year's form printed."""
    account, eur = _account(db), _eur(db)
    _staking_reward(db, account, eur, amount="300", occurred_at=_at(2024))

    forms = _forms(client, year=2024)

    income = _line(_section(forms, "so.leistungen"), "so.leistungen.einnahmen_krypto")
    assert income["form_lines"] == ["11"]
    assert income["label"] == (
        "Einnahmen im Zusammenhang mit Einheiten virtueller Währungen und / oder sonstigen Token:"
    )


def test_a_year_with_no_recorded_form_names_the_field_and_says_the_line_is_missing(db, client):
    """No line number is carried over from another year's form: a year
    whose form was never read still names the form and the field, states
    the figure, and says plainly that the line number is not mapped."""
    account, eur = _account(db), _eur(db)
    _staking_reward(db, account, eur, amount="300", occurred_at=_at(2026))

    forms = _forms(client, year=2026)

    assert forms["line_numbers_mapped"] is False
    leistungen = _section(forms, "so.leistungen")
    assert leistungen["form"] == "Anlage SO"
    income = _line(leistungen, "so.leistungen.einnahmen_krypto")
    assert income["form_lines"] == []
    assert income["mapping"] == "unmapped"
    assert income["label"] == "Einnahmen im Zusammenhang mit Kryptowerten:"
    assert "2026" in income["note"]
    assert Decimal(income["amount_eur"]) == Decimal("300")


def test_other_income_states_its_taxable_amount_and_never_a_euro_tax(db, client):
    """ADR-0007: §22 income is taxed at the personal marginal rate, which
    the application cannot know — the section shows the year's balance and
    the taxable amount the Freigrenze leaves, and states no tax owed."""
    account, eur = _account(db), _eur(db)
    _staking_reward(db, account, eur, amount="300", occurred_at=_at(2025))

    leistungen = _section(_forms(client, year=2025), "so.leistungen")

    balances = {balance["key"]: balance for balance in leistungen["balances"]}
    assert Decimal(balances["so.leistungen.einkuenfte"]["amount_eur"]) == Decimal("300")
    # 300 € reaches the 256 € Freigrenze (§22 Nr. 3 Satz 2 EStG): all taxable.
    assert Decimal(balances["so.leistungen.taxable"]["amount_eur"]) == Decimal("300")
    assert leistungen["tax"]["stated"] is False
    assert leistungen["tax"]["total_eur"] is None
    assert "marginal rate" in leistungen["tax"]["note"]


# --- Anlage SO: private Veräußerungsgeschäfte (§23 EStG) ---------------------


def _trade(db, account, *, give, given, get, gotten, occurred_at, fee=None):
    """One trade: `given` of `give` out, `gotten` of `get` in, an optional
    fee in the first-named cash charged against the disposed leg."""
    legs = [
        Leg(account_id=account, instrument_id=give, role="out", quantity=Decimal(given)),
        Leg(account_id=account, instrument_id=get, role="in", quantity=Decimal(gotten)),
    ]
    if fee is not None:
        legs.append(
            Leg(
                account_id=account,
                instrument_id=get,
                role="fee",
                quantity=Decimal(fee),
                charged_against=0,
            )
        )
    return _transaction(db, "trade", occurred_at, legs)


def test_one_crypto_sale_fills_the_crypto_block_line_by_line(db, client):
    """The 2025 Anlage SO's Kryptowerte block holds one disposal on Zeilen
    48 to 51: Veräußerungspreis, Anschaffungskosten, Werbungskosten and the
    Gewinn. 1 BTC bought for 10000 € and sold within the year for 12000 €
    with a 10 € fee: gain 1990 €."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    _trade(db, account, give=eur, given="10000", get=btc, gotten="1", occurred_at=_at(2025, 1))
    _trade(
        db,
        account,
        give=btc,
        given="1",
        get=eur,
        gotten="12000",
        fee="10",
        occurred_at=_at(2025, 6),
    )

    sales = _section(_forms(client, year=2025), "so.private_sales")

    assert sales["form"] == "Anlage SO"
    stated = {
        line["key"]: (line["form_lines"], Decimal(line["amount_eur"]), line["mapping"])
        for line in sales["lines"]
    }
    assert stated == {
        "so.krypto.veraeusserungspreis": (["48"], Decimal("12000"), "unambiguous"),
        "so.krypto.anschaffungskosten": (["49"], Decimal("10000"), "unambiguous"),
        "so.krypto.werbungskosten": (["50"], Decimal("10"), "unambiguous"),
        "so.krypto.gewinn": (["51"], Decimal("1990"), "unambiguous"),
    }
    balances = {balance["key"]: balance for balance in sales["balances"]}
    assert Decimal(balances["so.private_sales.gesamtgewinn"]["amount_eur"]) == Decimal("1990")
    # 1990 € reaches the 1000 € Freigrenze (§23 Abs. 3 Satz 5 EStG).
    assert Decimal(balances["so.private_sales.taxable"]["amount_eur"]) == Decimal("1990")
    assert sales["tax"]["stated"] is False
    assert sales["tax"]["total_eur"] is None


def test_several_crypto_sales_say_the_block_holds_only_one(db, client):
    """Each §23 block takes a single disposal; further ones belong on the
    further-disposals line by separate schedule (Zeile 59 in 2025). The
    block's figures are then the total of all of them, and the mapping says
    plainly that it is not one line's worth."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    _trade(db, account, give=eur, given="10000", get=btc, gotten="2", occurred_at=_at(2025, 1))
    _trade(db, account, give=btc, given="1", get=eur, gotten="6000", occurred_at=_at(2025, 5))
    _trade(db, account, give=btc, given="1", get=eur, gotten="7000", occurred_at=_at(2025, 6))

    sales = _section(_forms(client, year=2025), "so.private_sales")

    gain = _line(sales, "so.krypto.gewinn")
    assert Decimal(gain["amount_eur"]) == Decimal("3000")
    assert gain["mapping"] == "ambiguous"
    assert gain["form_lines"] == ["51", "59"]
    assert "2 disposals" in gain["note"]
    assert len(gain["backed_by"]) == 2
    # The block's own lines are a single disposal's too: a total of two is
    # not what Zeile 48 asks for, and says so.
    proceeds = _line(sales, "so.krypto.veraeusserungspreis")
    assert proceeds["form_lines"] == ["48"]
    assert proceeds["mapping"] == "ambiguous"
    assert "2 disposals" in proceeds["note"]


def test_a_sale_held_beyond_the_haltefrist_stays_off_the_form(db, client):
    """An exempt disposal is not declared: the block states only what
    counts, exactly as the year's total does."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    _trade(db, account, give=eur, given="10000", get=btc, gotten="1", occurred_at=_at(2023, 1))
    _trade(db, account, give=btc, given="1", get=eur, gotten="30000", occurred_at=_at(2025, 6))

    sales = _section(_forms(client, year=2025), "so.private_sales")

    assert sales["lines"] == []
    balances = {balance["key"]: balance for balance in sales["balances"]}
    assert Decimal(balances["so.private_sales.gesamtgewinn"]["amount_eur"]) == Decimal("0")


def test_a_foreign_currency_sale_goes_in_the_other_assets_block(db, client):
    """Foreign cash is no Kryptowert: its disposal belongs in "Andere
    Wirtschaftsgüter" — Zeilen 50 to 53 on the 2024 form."""
    account, eur = _account(db), _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    settled = stances.classify(db, usd, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    _trade(db, account, give=eur, given="1000", get=usd, gotten="1250", occurred_at=_at(2024, 1))
    _trade(db, account, give=usd, given="1250", get=eur, gotten="1100", occurred_at=_at(2024, 6))

    sales = _section(_forms(client, year=2024), "so.private_sales")

    stated = {
        line["key"]: (line["form_lines"], Decimal(line["amount_eur"])) for line in sales["lines"]
    }
    assert stated == {
        "so.andere.veraeusserungspreis": (["50"], Decimal("1100")),
        "so.andere.anschaffungskosten": (["51"], Decimal("1000")),
        "so.andere.werbungskosten": (["52"], Decimal("0")),
        "so.andere.gewinn": (["53"], Decimal("100")),
    }


# --- Anlage KAP: capital income (§20 EStG) -----------------------------------


def _depot(db, *, withholding="none", platform_name="Foreign broker", name="Depot"):
    """A Depot: an Account under a broker Platform whose withholding
    behaviour is set (ticket 43)."""
    platform_id = platforms.create_platform(db, name=platform_name, kind="broker")
    assert platforms.set_withholding(db, platform_id, behaviour=withholding) is None
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _security(db, *, type="share", symbol="SAP", isin="DE0007164600", category=None):
    return instruments.create_security(
        db,
        symbol=symbol,
        name=symbol,
        type=type,
        isin=isin,
        fund_category=category,
        fund_category_source="provider" if category is not None else None,
        distribution_policy="distributing" if category is not None else None,
    )


def _receive(db, account, cash, *, net, occurred_at, type="dividend", **declared):
    """One income Transaction: the net that arrived as its in-leg, and what
    the statement declares beyond it."""
    return _transaction(
        db,
        type,
        occurred_at,
        [Leg(account_id=account, instrument_id=cash, role="in", quantity=Decimal(net))],
        capital_income=CapitalIncome(
            **{
                key: value if key in ("paying_instrument_id", "source_country") else Decimal(value)
                for key, value in declared.items()
            }
        ),
    )


def _round_trip(db, account, security, eur, *, cost, proceeds, year):
    """Ten units of a kept position bought in January and sold in June of
    the year."""
    settled = stances.classify(db, security, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    _trade(db, account, give=eur, given=cost, get=security, gotten="10", occurred_at=_at(year, 1))
    _trade(
        db, account, give=security, given="10", get=eur, gotten=proceeds, occurred_at=_at(year, 6)
    )


def _amounts(section):
    return {line["key"]: Decimal(line["amount_eur"]) for line in section["lines"]}


def test_income_at_a_broker_that_withholds_nothing_is_to_declare_and_says_which_lines(db, client):
    """Anlage KAP splits income not taxed at source into inländische (Zeile
    18) and ausländische Kapitalerträge (Zeile 19) by the paying
    institution — a fact the ledger does not hold. The figure is stated
    once, naming both lines, and says plainly what decides between them."""
    depot, eur = _depot(db), _eur(db)
    _receive(db, depot, eur, net="40", occurred_at=_at(2025))

    kap = _section(_forms(client, year=2025), "kap")

    assert kap["form"] == "Anlage KAP"
    income = _line(kap, "kap.kapitalertraege")
    assert Decimal(income["amount_eur"]) == Decimal("40")
    assert income["form_lines"] == ["18", "19"]
    assert income["mapping"] == "ambiguous"
    assert income["side"] == "to_declare"
    assert "paying institution" in income["note"]


def test_sales_fill_the_included_gain_and_loss_lines(db, client):
    """Zeilen 20, 22 and 23 restate what Zeilen 18/19 already contain: share
    gains, losses other than from shares, and share losses — each loss as
    its amount. A share sold 500 € up, another 300 € down, a bond 100 € down
    and a 40 € dividend: 140 € net."""
    depot, eur = _depot(db), _eur(db)
    winner = _security(db)
    loser = _security(db, symbol="BMW", isin="DE0005190003")
    bond = _security(db, type="bond", symbol="BUND", isin="DE0001102580")
    _round_trip(db, depot, winner, eur, cost="1000", proceeds="1500", year=2025)
    _round_trip(db, depot, loser, eur, cost="1000", proceeds="700", year=2025)
    _round_trip(db, depot, bond, eur, cost="1000", proceeds="900", year=2025)
    _receive(db, depot, eur, net="40", occurred_at=_at(2025))

    kap = _section(_forms(client, year=2025), "kap")

    assert _amounts(kap) == {
        "kap.kapitalertraege": Decimal("140"),
        "kap.aktien_gewinne": Decimal("500"),
        "kap.verluste_ohne_aktien": Decimal("100"),
        "kap.aktien_verluste": Decimal("300"),
    }
    assert _line(kap, "kap.aktien_gewinne")["form_lines"] == ["20"]
    assert _line(kap, "kap.verluste_ohne_aktien")["form_lines"] == ["22"]
    assert _line(kap, "kap.aktien_verluste")["form_lines"] == ["23"]
    assert _line(kap, "kap.aktien_gewinne")["mapping"] == "unambiguous"


def _futures_close(client, account, eur, *, realized, year):
    created = client.post(
        "/api/futures/positions",
        json={
            "account_id": account,
            "symbol": "BTC-PERP",
            "side": "long",
            "quantity": "1",
            "settlement_instrument_id": eur,
            "opened_at": _at(year, 2).isoformat(),
            "closed_at": _at(year, 3).isoformat(),
            "realized": realized,
            "fees": "0",
        },
    )
    assert created.status_code == 201, created.text


def test_the_2024_form_keeps_termingeschaefte_on_lines_of_their_own(db, client):
    """The 2024 Anlage KAP still prints Zeile 21 for futures gains — inside
    Zeilen 18/19 — and Zeile 24 for futures losses, which its Zeilen 18/19
    exclude by their own label."""
    account, eur = _account(db), _eur(db)
    _futures_close(client, account, eur, realized="500", year=2024)
    _futures_close(client, account, eur, realized="-200", year=2024)

    kap = _section(_forms(client, year=2024), "kap")

    assert _amounts(kap) == {
        "kap.kapitalertraege": Decimal("500"),
        "kap.termingeschaefte_gewinne": Decimal("500"),
        "kap.termingeschaefte_verluste": Decimal("200"),
    }
    assert _line(kap, "kap.termingeschaefte_gewinne")["form_lines"] == ["21"]
    assert _line(kap, "kap.termingeschaefte_verluste")["form_lines"] == ["24"]


def test_the_2025_form_folds_termingeschaefte_into_the_general_lines(db, client):
    """The 2025 form dropped Zeilen 21 and 24 (JStG 2024): a futures loss
    is part of Zeilen 18/19 and restated on Zeile 22 like any other loss."""
    account, eur = _account(db), _eur(db)
    _futures_close(client, account, eur, realized="500", year=2025)
    _futures_close(client, account, eur, realized="-200", year=2025)

    kap = _section(_forms(client, year=2025), "kap")

    assert _amounts(kap) == {
        "kap.kapitalertraege": Decimal("300"),
        "kap.verluste_ohne_aktien": Decimal("200"),
    }


def test_amounts_withheld_at_source_stand_apart_from_amounts_to_declare(db, client):
    """A dividend the German broker already taxed is not declared again: it
    stands on the withheld side — Zeile 7, with the tax taken on Zeilen 37
    and 38 — while the foreign broker's dividend alone is to declare, its
    creditable Quellensteuer on Zeile 41."""
    capital_income_repository.upsert_treaty_limit(
        db, country="CH", rate=Decimal("0.15"), source="Art. 10 DBA-Schweiz"
    )
    eur = _eur(db)
    german = _depot(db, withholding="at_source", platform_name="German broker")
    foreign = _depot(db)
    _receive(
        db,
        german,
        eur,
        net="73.625",
        kapitalertragsteuer="25",
        solidarity_surcharge="1.375",
        occurred_at=_at(2025),
    )
    _receive(
        db,
        foreign,
        eur,
        net="50",
        foreign_withholding="35",
        source_country="CH",
        occurred_at=_at(2025),
    )

    kap = _section(_forms(client, year=2025), "kap")

    sides = {line["key"]: line["side"] for line in kap["lines"]}
    assert sides == {
        "kap.abzug.kapitalertraege": "withheld_at_source",
        "kap.kapitalertraege": "to_declare",
        "kap.steuer.kapitalertragsteuer": "withheld_at_source",
        "kap.steuer.solidaritaetszuschlag": "withheld_at_source",
        "kap.steuer.kirchensteuer": "withheld_at_source",
        "kap.steuer.auslaendische_anrechenbar": "to_declare",
    }
    assert _amounts(kap) == {
        "kap.abzug.kapitalertraege": Decimal("100"),
        "kap.kapitalertraege": Decimal("85"),
        "kap.steuer.kapitalertragsteuer": Decimal("25"),
        "kap.steuer.solidaritaetszuschlag": Decimal("1.375"),
        "kap.steuer.kirchensteuer": Decimal("0"),
        # 15 % of the 85 € gross is creditable (the treaty ceiling).
        "kap.steuer.auslaendische_anrechenbar": Decimal("12.75"),
    }
    assert _line(kap, "kap.abzug.kapitalertraege")["form_lines"] == ["7"]
    # Zeile 7 wants the broker's certified figure, which the ledger's own
    # only approximates — and the line says so.
    assert _line(kap, "kap.abzug.kapitalertraege")["mapping"] == "ambiguous"
    assert "Steuerbescheinigung" in _line(kap, "kap.abzug.kapitalertraege")["note"]
    assert _line(kap, "kap.steuer.kapitalertragsteuer")["form_lines"] == ["37"]
    assert _line(kap, "kap.steuer.solidaritaetszuschlag")["form_lines"] == ["38"]
    assert _line(kap, "kap.steuer.kirchensteuer")["form_lines"] == ["39"]
    assert _line(kap, "kap.steuer.auslaendische_anrechenbar")["form_lines"] == ["41"]


def test_capital_income_states_its_tax_because_the_rate_is_statutory(db, client):
    """ADR-0007: the flat rate is fixed in law, so this is the one section
    that states a euro tax. 5000 € less the 1000 € Sparerpauschbetrag
    leaves 4000 €: 1000 € at 25 % plus 55 € Solidaritätszuschlag. Each
    category's balance for the year stands beside it."""
    depot, eur = _depot(db), _eur(db)
    _receive(db, depot, eur, net="5000", occurred_at=_at(2025))

    kap = _section(_forms(client, year=2025), "kap")

    assert kap["tax"]["stated"] is True
    assert Decimal(kap["tax"]["income_tax_eur"]) == Decimal("1000")
    assert Decimal(kap["tax"]["solidarity_surcharge_eur"]) == Decimal("55")
    assert Decimal(kap["tax"]["total_eur"]) == Decimal("1055")
    assert "Günstigerprüfung" in kap["tax"]["note"]
    balances = {balance["key"]: Decimal(balance["amount_eur"]) for balance in kap["balances"]}
    assert balances == {
        "kap.balance.aktien": Decimal("0"),
        "kap.balance.sonstige": Decimal("5000"),
        "kap.balance.termingeschaefte": Decimal("0"),
        "kap.combined": Decimal("5000"),
        "kap.allowance_applied": Decimal("1000"),
        "kap.taxable": Decimal("4000"),
    }


def test_quellensteuer_is_split_by_whether_a_withholding_depot_already_credited_it(db, client):
    """Zeile 40 takes foreign tax the German broker already credited, Zeile
    41 what is still to credit — each receipt's own creditable part, on the
    side of the Depot that received it. Two 100 € dividends with 20 € Swiss
    tax each, the treaty allowing 15 %: 15 € on either line."""
    capital_income_repository.upsert_treaty_limit(
        db, country="CH", rate=Decimal("0.15"), source="Art. 10 DBA-Schweiz"
    )
    eur = _eur(db)
    german = _depot(db, withholding="at_source", platform_name="German broker")
    foreign = _depot(db)
    for depot in (german, foreign):
        _receive(
            db,
            depot,
            eur,
            net="80",
            foreign_withholding="20",
            source_country="CH",
            occurred_at=_at(2025),
        )

    kap = _section(_forms(client, year=2025), "kap")

    credited = _line(kap, "kap.steuer.auslaendische_angerechnet")
    creditable = _line(kap, "kap.steuer.auslaendische_anrechenbar")
    assert (credited["form_lines"], credited["side"]) == (["40"], "withheld_at_source")
    assert (creditable["form_lines"], creditable["side"]) == (["41"], "to_declare")
    assert Decimal(credited["amount_eur"]) == Decimal("15")
    assert Decimal(creditable["amount_eur"]) == Decimal("15")
    assert credited["mapping"] == creditable["mapping"] == "unambiguous"


def test_capital_income_awaiting_a_valuation_states_no_line_and_says_why(db, client):
    """A dividend paid in a coin no rate can value leaves the whole year's
    capital income unstated (services/section20): the Anlage KAP section
    carries no line, no tax, and a sentence naming what it waits on."""
    depot, eur = _depot(db), _eur(db)
    account = _account(db)
    sol = _kept_coin(db, account, symbol="SOL", chain="solana")
    _receive(db, depot, eur, net="40", occurred_at=_at(2025))
    _transaction(
        db,
        "dividend",
        _at(2025),
        [Leg(account_id=account, instrument_id=sol, role="in", quantity=Decimal("1"))],
    )

    forms = _forms(client, year=2025)

    kap = _section(forms, "kap")
    assert kap["lines"] == []
    assert kap["tax"]["stated"] is False
    assert "awaits a valuation" in kap["note"]
    assert "leg:" in kap["note"]
    assert "awaits a valuation" in _section(forms, "kapinv")["note"]


# --- Anlage KAP-INV: fund income not taxed at source -------------------------


def test_fund_income_goes_on_anlage_kap_inv_before_teilfreistellung(db, client):
    """Fund income a foreign broker did not tax belongs on Anlage KAP-INV by
    fund type, in full — the Finanzamt applies the Teilfreistellung — and
    stays off Anlage KAP's Zeilen 18/19. An Aktienfonds distributing 100 €
    and sold 400 € up: Zeile 4 and Zeile 14, although only 70 % of each
    enters its category."""
    depot, eur = _depot(db), _eur(db)
    fund = _security(db, type="etf", symbol="VWRL", isin="IE00B3RBWM25", category="aktienfonds")
    _round_trip(db, depot, fund, eur, cost="1000", proceeds="1400", year=2025)
    _receive(
        db,
        depot,
        eur,
        net="100",
        type="distribution",
        paying_instrument_id=fund,
        occurred_at=_at(2025),
    )

    forms = _forms(client, year=2025)

    funds = _section(forms, "kapinv")
    assert funds["form"] == "Anlage KAP-INV"
    assert _amounts(funds) == {
        "kapinv.ausschuettungen.aktienfonds": Decimal("100"),
        "kapinv.veraeusserung.aktienfonds": Decimal("400"),
    }
    assert _line(funds, "kapinv.ausschuettungen.aktienfonds")["form_lines"] == ["4"]
    assert _line(funds, "kapinv.veraeusserung.aktienfonds")["form_lines"] == ["14"]
    assert "Teilfreistellung" in _line(funds, "kapinv.ausschuettungen.aktienfonds")["label"]
    kap = _section(forms, "kap")
    assert "kap.kapitalertraege" not in _amounts(kap)
    balances = {balance["key"]: Decimal(balance["amount_eur"]) for balance in kap["balances"]}
    assert balances["kap.balance.sonstige"] == Decimal("350")
    assert funds["tax"]["stated"] is False


def test_each_fund_type_has_its_own_lines(db, client):
    """A Mischfonds distribution is Zeile 5, its sale Zeile 17."""
    depot, eur = _depot(db), _eur(db)
    fund = _security(db, type="fund", symbol="MIX", isin="LU0000000001", category="mischfonds")
    _round_trip(db, depot, fund, eur, cost="1000", proceeds="900", year=2025)
    _receive(
        db,
        depot,
        eur,
        net="20",
        type="distribution",
        paying_instrument_id=fund,
        occurred_at=_at(2025),
    )

    funds = _section(_forms(client, year=2025), "kapinv")

    assert _line(funds, "kapinv.ausschuettungen.mischfonds")["form_lines"] == ["5"]
    sale = _line(funds, "kapinv.veraeusserung.mischfonds")
    assert sale["form_lines"] == ["17"]
    # A loss on Anlage KAP-INV is a signed Gewinn / Verlust figure.
    assert Decimal(sale["amount_eur"]) == Decimal("-100")


# --- The exports: the same form figures, each backed by its lines ------------


def _report_id(client, *, year):
    generated = client.post("/api/reports", json={"year": year})
    assert generated.status_code == 201, generated.text
    return generated.json()["id"]


def _appendix(client, report_id):
    """The CSV split back into its summary pairs and its line-item table."""
    rows = list(csv.reader(io.StringIO(client.get(f"/api/reports/{report_id}/appendix.csv").text)))
    split = rows.index([])
    header, *lines = rows[split + 1 :]
    return dict(rows[:split]), [dict(zip(header, line, strict=True)) for line in lines]


def _backing(lines, key, column):
    """What the appendix lines feeding one form line add up to."""
    return sum(
        (Decimal(line[column]) for line in lines if key in line["form_line_keys"].split()),
        Decimal(0),
    )


def _mixed_year(db):
    """A year touching every form: two crypto sales, a share sold at a gain,
    a bond at a loss, a fund sold and distributing, and a 40 € dividend that
    arrived with German tax already taken — all at a Depot that itself
    withholds nothing."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    _trade(db, account, give=eur, given="10000", get=btc, gotten="2", occurred_at=_at(2025, 1))
    _trade(db, account, give=btc, given="1", get=eur, gotten="6000", occurred_at=_at(2025, 5))
    _trade(db, account, give=btc, given="1", get=eur, gotten="7000", occurred_at=_at(2025, 6))
    _staking_reward(db, account, eur, amount="300", occurred_at=_at(2025))
    depot = _depot(db)
    share = _security(db)
    fund = _security(db, type="etf", symbol="VWRL", isin="IE00B3RBWM25", category="aktienfonds")
    _round_trip(db, depot, share, eur, cost="1000", proceeds="1500", year=2025)
    _round_trip(db, depot, fund, eur, cost="1000", proceeds="1400", year=2025)
    bond = _security(db, type="bond", symbol="BUND", isin="DE0001102580")
    _round_trip(db, depot, bond, eur, cost="1000", proceeds="900", year=2025)
    _receive(
        db,
        depot,
        eur,
        net="13.625",
        kapitalertragsteuer="25",
        solidarity_surcharge="1.375",
        occurred_at=_at(2025),
    )
    _receive(
        db,
        depot,
        eur,
        net="100",
        type="distribution",
        paying_instrument_id=fund,
        occurred_at=_at(2025),
    )


def test_the_appendix_restates_every_form_line_with_where_it_goes(db, client):
    """The export's summary carries each form figure in cents beside the
    line it belongs on — the form and Zeile where unambiguous, both
    candidates where not."""
    _mixed_year(db)

    summary, _ = _appendix(client, _report_id(client, year=2025))

    assert summary["form.so.leistungen.einnahmen_krypto.line"] == "Anlage SO Zeile 15"
    assert summary["form.so.leistungen.einnahmen_krypto.eur"] == "300.00"
    assert summary["form.so.krypto.gewinn.line"] == "Anlage SO Zeile 51 or 59 (ambiguous)"
    assert summary["form.so.krypto.gewinn.eur"] == "3000.00"
    assert summary["form.so.krypto.veraeusserungspreis.line"] == "Anlage SO Zeile 48 (ambiguous)"
    assert summary["form.kap.kapitalertraege.line"] == "Anlage KAP Zeile 18 or 19 (ambiguous)"
    # 500 € share gain, 100 € bond loss, 40 € dividend.
    assert summary["form.kap.kapitalertraege.eur"] == "440.00"
    assert summary["form.kap.aktien_gewinne.line"] == "Anlage KAP Zeile 20"
    assert summary["form.kap.aktien_gewinne.eur"] == "500.00"
    assert summary["form.kapinv.ausschuettungen.aktienfonds.line"] == "Anlage KAP-INV Zeile 4"
    assert summary["form.kapinv.ausschuettungen.aktienfonds.eur"] == "100.00"
    assert summary["form.kapinv.veraeusserung.aktienfonds.eur"] == "400.00"


def test_every_form_figure_is_backed_by_the_appendix_lines_that_feed_it(db, client):
    """Each appendix line names the form lines it feeds, and the lines
    feeding one form line add up to the figure stated for it: a private
    sale's proceeds, basis and gain; a §22 receipt's value; a capital
    event's gross — before Teilfreistellung, as the fund lines want it."""
    _mixed_year(db)

    summary, lines = _appendix(client, _report_id(client, year=2025))

    for key, column in (
        ("so.leistungen.einnahmen_krypto", "amount_eur"),
        ("so.krypto.veraeusserungspreis", "proceeds_eur"),
        ("so.krypto.anschaffungskosten", "basis_eur"),
        ("so.krypto.werbungskosten", "fees_eur"),
        ("so.krypto.gewinn", "amount_eur"),
        ("kap.kapitalertraege", "gross_eur"),
        ("kap.aktien_gewinne", "gross_eur"),
        ("kapinv.ausschuettungen.aktienfonds", "gross_eur"),
        ("kapinv.veraeusserung.aktienfonds", "gross_eur"),
    ):
        assert _backing(lines, key, column) == Decimal(summary[f"form.{key}.eur"]), key
    # A loss line states the loss as its amount; the lines behind it carry
    # the signed result.
    assert summary["form.kap.verluste_ohne_aktien.eur"] == "100.00"
    assert _backing(lines, "kap.verluste_ohne_aktien", "gross_eur") == Decimal("-100.00")
    # Tax taken at source is backed by what each receipt had withheld.
    for key, column in (
        ("kap.steuer.kapitalertragsteuer", "kapitalertragsteuer_eur"),
        ("kap.steuer.solidaritaetszuschlag", "solidarity_surcharge_eur"),
        ("kap.steuer.kirchensteuer", "church_tax_eur"),
    ):
        assert _backing(lines, key, column) == Decimal(summary[f"form.{key}.eur"]), key
    assert summary["form.kap.steuer.kapitalertragsteuer.eur"] == "25.00"
    # The fund's distribution enters its category at 70 %, and is still
    # declared in full.
    (distribution,) = [
        line for line in lines if "kapinv.ausschuettungen.aktienfonds" in line["form_line_keys"]
    ]
    assert distribution["amount_eur"] == "70.00"
    assert distribution["gross_eur"] == "100.00"


def test_an_exempt_slice_feeds_no_form_line(db, client):
    """A lot slice held beyond the Haltefrist is shown in the appendix and
    declared nowhere."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    _trade(db, account, give=eur, given="10000", get=btc, gotten="1", occurred_at=_at(2023, 1))
    _trade(db, account, give=btc, given="1", get=eur, gotten="30000", occurred_at=_at(2025, 6))

    _, lines = _appendix(client, _report_id(client, year=2025))

    (exempt,) = lines
    assert exempt["treatment"] == "exempt"
    assert exempt["form_line_keys"] == ""


def test_the_pdf_states_the_same_form_figures_as_the_csv(db, client):
    """Both exports render the one appendix: every form line's location and
    figure in the CSV summary appears in the PDF."""
    _mixed_year(db)
    report_id = _report_id(client, year=2025)

    summary, _ = _appendix(client, report_id)
    pdf = client.get(f"/api/reports/{report_id}/appendix.pdf")

    assert pdf.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    form_entries = {label: value for label, value in summary.items() if label.startswith("form.")}
    assert form_entries
    for label, value in form_entries.items():
        for word in value.split():
            assert word in text, f"{label}={value} missing from the PDF"


def test_an_unmapped_year_s_export_says_the_line_is_not_mapped(db, client):
    account, eur = _account(db), _eur(db)
    _staking_reward(db, account, eur, amount="300", occurred_at=_at(2026))

    summary, _ = _appendix(client, _report_id(client, year=2026))

    assert summary["form.so.leistungen.einnahmen_krypto.line"] == (
        "Anlage SO (line not mapped for 2026)"
    )
    assert summary["form.so.leistungen.einnahmen_krypto.eur"] == "300.00"


# --- Awaiting valuation: carried, never guessed ------------------------------


def test_a_form_line_awaiting_a_valuation_states_no_figure(db, client):
    """A crypto-for-crypto sale whose proceeds no rate can state leaves its
    form lines without an amount — in the report and in the export — rather
    than a number computed around the gap."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    sol = _kept_coin(db, account, symbol="SOL", chain="solana")
    _trade(db, account, give=eur, given="1000", get=btc, gotten="1", occurred_at=_at(2025, 1))
    _trade(db, account, give=btc, given="1", get=sol, gotten="10", occurred_at=_at(2025, 6))
    report_id = _report_id(client, year=2025)

    forms = client.get(f"/api/reports/{report_id}").json()["figures"]["forms"]
    summary, _ = _appendix(client, report_id)

    gain = _line(_section(forms, "so.private_sales"), "so.krypto.gewinn")
    assert gain["amount_eur"] is None
    assert gain["form_lines"] == ["51"]
    assert summary["form.so.krypto.gewinn.eur"] == "awaiting valuation"
