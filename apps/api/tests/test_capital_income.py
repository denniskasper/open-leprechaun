"""Dividends, distributions and withholding taxes (ticket 47): income from
securities is recorded gross with every tax already taken out of it — the
ledger's in-leg stays the net that arrived, the Transaction's capital-income
declaration states what was withheld and by whom — and each receipt reduces
to one Section 20 Event carrying both withholdings, computing no tax of its
own (ADR-0013).

The seams are the §20 engine's one public read — `section20.year_report`,
driven over real Postgres with the ledger built through the repositories and
rates through a fake of the reference-rate port — the producer's own detail
read (`capital_income.receipts_through`), the engine's pure
`section20.withholding_statement`, and the named refusals.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import (
    capital_income as capital_income_repository,
)
from open_leprechaun.repositories import instruments, platforms, stances, statutory, transactions
from open_leprechaun.repositories.transactions import CapitalIncome, Leg
from open_leprechaun.services import capital_income, section20
from open_leprechaun.services.security_disposals import UnclassifiedSecurityError

RECEIVED = datetime(2031, 5, 14, 12, 0, tzinfo=UTC)


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
def store(db):
    """The migrated database with this file's statutory mutation years wiped —
    statutory rows outlive the shared `db` fixture, which resets only the
    ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


def _statutes(store, *, year=2031):
    """The values the §20 assessment reads for a year no migration seeds."""
    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
        ("partial_exemption_aktienfonds", "0.30"),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="a test value"
        )


def _depot(db, *, withholding, platform_name="Broker", name="Depot"):
    platform_id = platforms.create_platform(db, name=platform_name, kind="broker")
    assert platforms.set_withholding(db, platform_id, behaviour=withholding) is None
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _usd(db):
    return instruments.create_cash(db, symbol="USD", name="US Dollar")


def _keep(db, instrument, account):
    """Foreign cash counts as income exactly when its leg mints a lot — a
    kept position (services/stances)."""
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _share(db, symbol="SAP", isin="DE0007164600"):
    return instruments.create_security(db, symbol=symbol, name=symbol, type="share", isin=isin)


def _fund(db, *, category, symbol="VWRL", isin="IE00B3RBWM25"):
    return instruments.create_security(
        db,
        symbol=symbol,
        name=symbol,
        type="etf",
        isin=isin,
        fund_category=category,
        fund_category_source="provider" if category is not None else None,
        distribution_policy="distributing" if category is not None else None,
    )


def _receive(db, account, cash, *, net, type="dividend", occurred_at=RECEIVED, **declared):
    """One income Transaction: the net that arrived as its in-leg, and what
    the statement declares beyond it."""
    created = transactions.create_transaction(
        db,
        type=type,
        occurred_at=occurred_at,
        note=None,
        legs=[Leg(account_id=account, instrument_id=cash, role="in", quantity=Decimal(net))],
        capital_income=CapitalIncome(
            **{
                key: value if key in ("paying_instrument_id", "source_country") else Decimal(value)
                for key, value in declared.items()
            }
        ),
    )
    assert isinstance(created, int)
    return created


def _sonstige_events(report):
    (pot,) = [balance for balance in report.balances if balance.category == "sonstige"]
    return [entry.event for entry in pot.entries]


def test_a_dividend_taxed_at_source_is_grossed_up_with_the_german_tax_split(store):
    """§43 Abs. 1 Satz 1 Nr. 1, §43a Abs. 1 EStG: the broker pays out the net
    — the event states the gross, the net plus everything withheld, and the
    German tax split into Kapitalertragsteuer, Solidaritätszuschlag and
    church tax, never one lump."""
    _statutes(store)
    depot, eur = _depot(store, withholding="at_source"), _eur(store)
    _receive(
        store,
        depot,
        eur,
        net="73.40",
        paying_instrument_id=_share(store),
        kapitalertragsteuer="24.45",
        solidarity_surcharge="1.34",
        church_tax="0.81",
    )

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    (event,) = _sonstige_events(report)
    assert event.gross_eur == Decimal("100.00")
    assert event.german_withholding == section20.GermanWithholding(
        kapitalertragsteuer_eur=Decimal("24.45"),
        solidarity_surcharge_eur=Decimal("1.34"),
        church_tax_eur=Decimal("0.81"),
    )
    assert event.foreign_withholding is None
    assert event.date == date(2031, 5, 14)


def test_a_foreign_dividend_carries_its_quellensteuer_and_country_at_the_event_date_s_rate(store):
    """§32d Abs. 5 EStG, ADR-0017: the Quellensteuer travels with its source
    country, and the gross — net plus what the source country kept — converts
    at the reference rate of the day it was received."""
    _statutes(store)
    capital_income_repository.upsert_treaty_limit(
        store, country="US", rate=Decimal("0.15"), source="Art. 10 DBA-USA"
    )
    depot, usd = _depot(store, withholding="none"), _usd(store)
    _keep(store, usd, depot)
    _receive(store, depot, usd, net="85", foreign_withholding="15", source_country="US")
    rates = FakeReferenceRateSource(
        [ReferenceRate(currency="USD", rate_date=date(2031, 5, 14), rate=Decimal("1.25"))]
    )

    report = section20.year_report(store, rates, year=2031)

    (event,) = _sonstige_events(report)
    assert event.gross_eur == Decimal("80")
    assert event.foreign_withholding == section20.ForeignWithholding(
        amount_eur=Decimal("12"), country="US"
    )
    assert event.german_withholding == section20.NO_GERMAN_WITHHOLDING


def _dividend_event(*, gross, withheld, country, exemption_rate="0"):
    return section20.Section20Event(
        date=date(2031, 5, 14),
        category="sonstige",
        gross_eur=Decimal(gross),
        exemption_rate=Decimal(exemption_rate),
        german_withholding=section20.NO_GERMAN_WITHHOLDING,
        foreign_withholding=section20.ForeignWithholding(
            amount_eur=Decimal(withheld), country=country
        ),
        source="leg:1",
    )


def test_quellensteuer_within_the_treaty_limit_is_creditable_in_full():
    """§32d Abs. 5 Satz 1 EStG: foreign tax is credited up to what the treaty
    lets the source country keep — 15 of a 100 € US dividend at the 15 %
    limit is creditable entire, nothing to reclaim."""
    statement = section20.withholding_statement(
        [_dividend_event(gross="100", withheld="15", country="US")],
        year=2031,
        treaty_limits={"US": Decimal("0.15")},
    )

    (credit,) = statement.foreign
    assert credit.country == "US"
    assert credit.withheld_eur == Decimal("15")
    assert credit.creditable_eur == Decimal("15")
    assert credit.reclaimable_eur == Decimal(0)


def test_quellensteuer_beyond_the_treaty_limit_is_reclaimable_from_the_source_country():
    """§32d Abs. 5 Satz 2 EStG: tax the source country kept beyond its
    treaty share is never credited here — of 35 withheld on a 100 € Swiss
    dividend, 15 is creditable and 20 is Switzerland's to refund. The
    statement names the country; it pursues nothing."""
    statement = section20.withholding_statement(
        [_dividend_event(gross="100", withheld="35", country="CH")],
        year=2031,
        treaty_limits={"CH": Decimal("0.15")},
    )

    (credit,) = statement.foreign
    assert credit.treaty_rate == Decimal("0.15")
    assert credit.creditable_eur == Decimal("15.00")
    assert credit.reclaimable_eur == Decimal("20.00")


def test_creditability_is_judged_per_dividend_and_stated_per_country():
    """A generous dividend never lends its unused treaty room to another:
    each event is limited on its own gross, then the country's figures
    sum."""
    statement = section20.withholding_statement(
        [
            _dividend_event(gross="100", withheld="35", country="CH"),
            _dividend_event(gross="100", withheld="5", country="CH"),
            _dividend_event(gross="200", withheld="30", country="US"),
        ],
        year=2031,
        treaty_limits={"CH": Decimal("0.15"), "US": Decimal("0.15")},
    )

    swiss, american = statement.foreign
    assert (swiss.country, swiss.creditable_eur, swiss.reclaimable_eur) == (
        "CH",
        Decimal("20.00"),
        Decimal("20.00"),
    )
    assert (american.country, american.creditable_eur) == ("US", Decimal("30"))


def test_a_country_with_no_treaty_limit_entered_refuses_by_name():
    """Creditability depends on which country withheld (CONTEXT.md): with no
    limit entered for it the statement refuses rather than crediting
    everything or nothing."""
    with pytest.raises(section20.TreatyLimitUnsetError, match="JP"):
        section20.withholding_statement(
            [_dividend_event(gross="100", withheld="15", country="JP")],
            year=2031,
            treaty_limits={},
        )


def test_the_statement_totals_the_german_tax_withheld_by_component():
    """§36 Abs. 2 Nr. 2 EStG: what was withheld at source is stated per
    component, the year's events summed — other years' stay out."""
    taxed = section20.Section20Event(
        date=date(2031, 5, 14),
        category="sonstige",
        gross_eur=Decimal("100"),
        exemption_rate=Decimal(0),
        german_withholding=section20.GermanWithholding(
            Decimal("24.45"), Decimal("1.34"), Decimal("0.81")
        ),
        foreign_withholding=None,
        source="leg:1",
    )
    earlier = section20.Section20Event(**{**taxed.__dict__, "date": date(2030, 5, 14)})

    statement = section20.withholding_statement(
        [taxed, taxed, earlier], year=2031, treaty_limits={}
    )

    assert statement.german == section20.GermanWithholding(
        Decimal("48.90"), Decimal("2.68"), Decimal("1.62")
    )
    assert statement.foreign == ()


def test_the_year_states_its_withholding_beside_the_pots(store):
    """The report's own read carries the statement: German tax at source by
    component, and the source country's Quellensteuer judged against the
    limit the Admin entered for it."""
    _statutes(store)
    capital_income_repository.upsert_treaty_limit(
        store, country="CH", rate=Decimal("0.15"), source="Art. 10 DBA-Schweiz"
    )
    depot, eur = _depot(store, withholding="at_source"), _eur(store)
    _receive(
        store,
        depot,
        eur,
        net="50",
        foreign_withholding="35",
        source_country="CH",
        kapitalertragsteuer="14.22",
        solidarity_surcharge="0.78",
    )

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.withholding.german.kapitalertragsteuer_eur == Decimal("14.22")
    (swiss,) = report.withholding.foreign
    assert swiss.creditable_eur == Decimal("15.00")
    assert swiss.reclaimable_eur == Decimal("20.00")


def test_a_year_with_an_unjudgeable_quellensteuer_refuses(store):
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    _receive(store, depot, eur, net="85", foreign_withholding="15", source_country="JP")

    with pytest.raises(section20.TreatyLimitUnsetError, match="JP"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_a_fund_distribution_carries_its_teilfreistellung_before_entering_its_pot(store):
    """§20 Abs. 1 InvStG: 30 % of an equity fund's distribution is exempt —
    the event states the gross and the fund's rate, and only the taxable
    share is pooled."""
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    fund = _fund(store, category="aktienfonds")
    _receive(store, depot, eur, net="100", type="distribution", paying_instrument_id=fund)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    (pot,) = [balance for balance in report.balances if balance.category == "sonstige"]
    (entry,) = pot.entries
    assert entry.event.gross_eur == Decimal("100")
    assert entry.event.exemption_rate == Decimal("0.30")
    assert entry.counted_eur == Decimal("70.00")


def test_a_share_s_dividend_carries_no_teilfreistellung(store):
    """§20 InvStG exempts fund income alone: a share's dividend enters its
    pot whole."""
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    _receive(store, depot, eur, net="100", paying_instrument_id=_share(store))

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    (event,) = _sonstige_events(report)
    assert event.exemption_rate == Decimal(0)


def test_a_distribution_naming_no_fund_refuses_rather_than_assuming_no_exemption(store):
    """Ticket 44's rule, extended: nothing silently assumes a zero
    exemption — a distribution is a fund's, and one that cannot say which
    fund cannot state its exempt share."""
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    _receive(store, depot, eur, net="100", type="distribution")

    with pytest.raises(UnclassifiedSecurityError, match="names no paying fund"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_a_distribution_from_an_unclassified_fund_refuses_by_name(store):
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    fund = _fund(store, category=None, symbol="MYST")
    _receive(store, depot, eur, net="100", type="distribution", paying_instrument_id=fund)

    with pytest.raises(UnclassifiedSecurityError, match="MYST"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_income_settled_at_source_is_distinguished_from_income_still_to_declare(store):
    """§43 Abs. 5 Satz 1 EStG: tax withheld at source settles the income; a
    broker that withholds nothing leaves it all for the return (§32d Abs. 3
    EStG). The year states each side's gross, and every receipt says which
    side it fell on — the Depot's withholding behaviour decides (ticket 43)."""
    _statutes(store)
    eur = _eur(store)
    german = _depot(store, withholding="at_source", platform_name="German broker")
    foreign = _depot(store, withholding="none", platform_name="Foreign broker")
    _receive(
        store, german, eur, net="73.625", kapitalertragsteuer="25", solidarity_surcharge="1.375"
    )
    _receive(store, foreign, eur, net="40")
    _receive(store, foreign, eur, net="2.50", type="interest")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.settled_at_source_eur == Decimal("100.000")
    assert report.to_declare_eur == Decimal("42.50")
    assert [receipt.settled_at_source for receipt in report.receipts] == [True, False, False]


def test_a_receipt_records_gross_both_withholdings_and_net(store):
    """The producer's own read: each dividend states gross, Quellensteuer
    with its country, German tax by component, and net received."""
    _statutes(store)
    depot, eur = _depot(store, withholding="at_source"), _eur(store)
    share = _share(store)
    _receive(
        store,
        depot,
        eur,
        net="62.10",
        paying_instrument_id=share,
        foreign_withholding="15",
        source_country="US",
        kapitalertragsteuer="10",
        solidarity_surcharge="0.55",
        church_tax="0.80",
    )

    (receipt,) = capital_income.receipts_through(
        store, FakeReferenceRateSource(), through_year=2031
    ).counted

    assert receipt.type == "dividend"
    assert receipt.paying_instrument_id == share
    assert receipt.gross_eur == Decimal("88.45")
    assert receipt.foreign_withholding_eur == Decimal("15")
    assert receipt.source_country == "US"
    assert receipt.kapitalertragsteuer_eur == Decimal("10")
    assert receipt.solidarity_surcharge_eur == Decimal("0.55")
    assert receipt.church_tax_eur == Decimal("0.80")
    assert receipt.net_eur == Decimal("62.10")


def test_interest_is_routed_to_the_other_income_category(store):
    """§20 Abs. 1 Nr. 7 EStG: interest is general capital income."""
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    _receive(store, depot, eur, net="12.34", type="interest")

    (receipt,) = capital_income.receipts_through(
        store, FakeReferenceRateSource(), through_year=2031
    ).counted

    assert receipt.category == "sonstige"
    assert receipt.exemption_rate == Decimal(0)


# --- The API: declaring what was withheld, and the treaty limits ------------


def _dividend_payload(account, cash, **capital_income):
    return {
        "type": "dividend",
        "occurred_at": RECEIVED.isoformat(),
        "legs": [{"account_id": account, "instrument_id": cash, "role": "in", "quantity": "85"}],
        "capital_income": capital_income,
    }


def test_a_dividend_is_recorded_and_answered_with_what_was_withheld(db, client):
    """The ledger answers the declaration as it was made — fixed-point
    strings in both directions, like every monetary value in the API."""
    depot, usd, share = _depot(db, withholding="none"), _usd(db), _share(db)
    payload = _dividend_payload(
        depot,
        usd,
        paying_instrument_id=share,
        foreign_withholding="15",
        source_country="US",
    )

    created = client.post("/api/transactions", json=payload)

    assert created.status_code == 201
    (recorded,) = client.get("/api/transactions").json()
    assert recorded["capital_income"] == {
        "paying_instrument_id": share,
        "foreign_withholding": "15",
        "source_country": "US",
        "kapitalertragsteuer": "0",
        "solidarity_surcharge": "0",
        "church_tax": "0",
    }


def test_a_transaction_declaring_nothing_answers_no_capital_income(db, client):
    depot, eur = _depot(db, withholding="none"), _eur(db)
    payload = _dividend_payload(depot, eur)
    del payload["capital_income"]

    assert client.post("/api/transactions", json=payload).status_code == 201

    (recorded,) = client.get("/api/transactions").json()
    assert recorded["capital_income"] is None


def test_a_quellensteuer_without_its_source_country_is_refused(db, client):
    """Creditability depends on which country withheld (CONTEXT.md): the
    amount and the country are recorded together or not at all."""
    depot, usd = _depot(db, withholding="none"), _usd(db)

    nameless = client.post(
        "/api/transactions", json=_dividend_payload(depot, usd, foreign_withholding="15")
    )
    amountless = client.post(
        "/api/transactions", json=_dividend_payload(depot, usd, source_country="US")
    )

    assert nameless.status_code == 422
    assert "source country" in nameless.json()["detail"]
    assert amountless.status_code == 422


def test_only_capital_income_declares_withholding(db, client):
    """A trade has no payer and nothing withheld at source — the declaration
    on any other type would be a figure no engine reads."""
    depot, eur, share = _depot(db, withholding="none"), _eur(db), _share(db)
    payload = {
        "type": "trade",
        "occurred_at": RECEIVED.isoformat(),
        "legs": [
            {"account_id": depot, "instrument_id": share, "role": "in", "quantity": "1"},
            {"account_id": depot, "instrument_id": eur, "role": "out", "quantity": "100"},
        ],
        "capital_income": {"kapitalertragsteuer": "5"},
    }

    refused = client.post("/api/transactions", json=payload)

    assert refused.status_code == 422
    assert "dividend, a distribution or interest" in refused.json()["detail"]


def test_a_declaration_describes_exactly_one_received_leg(db, client):
    """The withheld amounts are denominated in the received leg's Instrument
    — with two in-legs nothing says which one they gross up."""
    depot, eur, usd = _depot(db, withholding="none"), _eur(db), _usd(db)
    payload = _dividend_payload(depot, usd, kapitalertragsteuer="5")
    payload["legs"].append(
        {"account_id": depot, "instrument_id": eur, "role": "in", "quantity": "1"}
    )

    refused = client.post("/api/transactions", json=payload)

    assert refused.status_code == 422
    assert "one received leg" in refused.json()["detail"]


def test_a_declaring_dividend_cannot_be_retyped_into_something_that_declares_nothing(db, client):
    depot, eur = _depot(db, withholding="none"), _eur(db)
    created = client.post(
        "/api/transactions", json=_dividend_payload(depot, eur, kapitalertragsteuer="5")
    ).json()["id"]

    to_airdrop = client.post(
        "/api/transactions/bulk-retyping", json={"transaction_ids": [created], "type": "airdrop"}
    )
    to_interest = client.post(
        "/api/transactions/bulk-retyping", json={"transaction_ids": [created], "type": "interest"}
    )

    assert to_airdrop.status_code == 422
    assert to_interest.status_code == 204


def test_revising_a_dividend_replaces_its_declaration(db, client):
    depot, eur = _depot(db, withholding="none"), _eur(db)
    created = client.post(
        "/api/transactions", json=_dividend_payload(depot, eur, kapitalertragsteuer="5")
    ).json()["id"]
    revised = _dividend_payload(depot, eur)
    del revised["capital_income"]

    assert client.put(f"/api/transactions/{created}", json=revised).status_code == 204

    (recorded,) = client.get("/api/transactions").json()
    assert recorded["capital_income"] is None


def test_treaty_limits_are_entered_with_a_cited_source_listed_and_removed(db, client):
    """Configuration with a source, never a constant in logic — and a rate
    is a fraction of one, as everywhere in the statutory store."""
    entered = client.put(
        "/api/treaty-limits/US", json={"rate": "0.15", "source": "Art. 10 Abs. 2 DBA-USA"}
    )
    as_percentage = client.put("/api/treaty-limits/CH", json={"rate": "15", "source": "a typo"})
    malformed = client.put("/api/treaty-limits/usa", json={"rate": "0.15", "source": "x"})

    assert entered.status_code == 204
    assert as_percentage.status_code == 422
    assert malformed.status_code == 422
    assert client.get("/api/treaty-limits").json() == [
        {"country": "US", "rate": "0.15", "source": "Art. 10 Abs. 2 DBA-USA"}
    ]
    assert client.delete("/api/treaty-limits/US").status_code == 204
    assert client.delete("/api/treaty-limits/US").status_code == 404
    assert client.get("/api/treaty-limits").json() == []


def test_correcting_a_withheld_amount_marks_the_report_resting_on_it_stale(store, client):
    """ADR-0014: the declaration is a figure's input exactly as a leg is —
    revising it after generation makes the report confess it is stale,
    naming the class that moved."""
    _statutes(store)
    depot, eur = _depot(store, withholding="at_source"), _eur(store)
    created = client.post(
        "/api/transactions", json=_dividend_payload(depot, eur, kapitalertragsteuer="5")
    ).json()["id"]
    for key, value in (
        ("private_sale_exemption_limit", "1000"),
        ("other_income_exemption_limit", "256"),
    ):
        statutory.upsert_value(store, year=2031, key=key, value=Decimal(value), source="a test")
    generated = client.post("/api/reports", json={"year": 2031})
    assert generated.status_code == 201, generated.text

    client.put(
        f"/api/transactions/{created}",
        json=_dividend_payload(depot, eur, kapitalertragsteuer="6"),
    )

    report = client.get(f"/api/reports/{generated.json()['id']}").json()
    assert report["stale"] is True
    assert "capital_income" in {entry["input_class"] for entry in report["changed_inputs"]}


def test_the_appendix_states_what_was_settled_withheld_creditable_and_reclaimable(store, client):
    """The export restates the frozen withholding figures: amounts settled
    at source apart from amounts to declare, German tax by component, and
    each source country's creditable and reclaimable Quellensteuer."""
    _statutes(store)
    for key, value in (
        ("private_sale_exemption_limit", "1000"),
        ("other_income_exemption_limit", "256"),
    ):
        statutory.upsert_value(store, year=2031, key=key, value=Decimal(value), source="a test")
    capital_income_repository.upsert_treaty_limit(
        store, country="CH", rate=Decimal("0.15"), source="Art. 10 DBA-Schweiz"
    )
    eur = _eur(store)
    german = _depot(store, withholding="at_source", platform_name="German broker")
    foreign = _depot(store, withholding="none", platform_name="Foreign broker")
    _receive(
        store,
        german,
        eur,
        net="50",
        foreign_withholding="35",
        source_country="CH",
        kapitalertragsteuer="14.22",
        solidarity_surcharge="0.78",
    )
    _receive(store, foreign, eur, net="40")
    report_id = client.post("/api/reports", json={"year": 2031}).json()["id"]

    exported = client.get(f"/api/reports/{report_id}/appendix.csv").text

    summary = dict(
        line.split(",", 1) for line in exported.split("\n\n")[0].splitlines() if "," in line
    )
    assert summary["section20.settled_at_source_eur"] == "100.00"
    assert summary["section20.to_declare_eur"] == "40.00"
    assert summary["section20.withheld.kapitalertragsteuer_eur"] == "14.22"
    assert summary["section20.withheld.solidarity_surcharge_eur"] == "0.78"
    assert summary["section20.withheld.church_tax_eur"] == "0.00"
    assert summary["section20.quellensteuer.CH.creditable_eur"] == "15.00"
    assert summary["section20.quellensteuer.CH.reclaimable_eur"] == "20.00"


def test_a_distribution_paid_by_something_other_than_a_fund_refuses(store):
    """A distribution is a fund's: one naming a share as its payer cannot
    state an exempt share any more than one naming nothing."""
    _statutes(store)
    depot, eur = _depot(store, withholding="none"), _eur(store)
    _receive(store, depot, eur, net="100", type="distribution", paying_instrument_id=_share(store))

    with pytest.raises(UnclassifiedSecurityError, match="names no paying fund"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_the_api_refuses_a_distribution_that_names_no_fund(db, client):
    depot, eur = _depot(db, withholding="none"), _eur(db)
    payload = _dividend_payload(depot, eur)
    payload["type"] = "distribution"

    refused = client.post("/api/transactions", json=payload)

    assert refused.status_code == 422
    assert "names the fund" in refused.json()["detail"]
