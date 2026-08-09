"""The §20 EStG capital-income engine, first half (ticket 26): one Section 20
Event shape every source of capital income reduces to, and the engine that
groups a year's events by Verlustverrechnungstopf, nets within each, and
applies that category's per-year loss cap from the statutory store — never a
constant in logic (ADR-0013).

Two seams: the pure engine (`section20.net` — events and configuration in,
per-category balances out, no database), and `year_report` over real
Postgres, which reduces the ledger's §20-typed income to events and reads
the caps. The report seam itself is tests/test_reports.py's.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.repositories import instruments, platforms, stances, statutory, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import section20

A_DAY = date(2025, 6, 15)

# The statutory mutation years: 2030+ like test_statutory.py, so the
# migration-seeded rows other files rely on stay pristine across runs.
RECEIVED_2031 = datetime(2031, 3, 14, 12, 0, tzinfo=UTC)


def _event(category, gross, *, on=A_DAY, rate="0", source="leg:1"):
    """A Section 20 Event as a producer would emit it — withholding empty
    until ticket 43 wires the amounts actually taken at source."""
    return section20.Section20Event(
        date=on,
        category=category,
        gross_eur=Decimal(gross),
        exemption_rate=Decimal(rate),
        german_withholding=section20.NO_GERMAN_WITHHOLDING,
        foreign_withholding=None,
        source=source,
    )


def _balances(events, *, year=2025, caps=None):
    """The engine's answer keyed by category, for assertions by name."""
    return {
        balance.category: balance for balance in section20.net(events, year=year, caps=caps or {})
    }


# --- The three Verlustverrechnungstöpfe, separate at every stage -------------


def test_a_year_nets_within_each_category_and_never_across():
    """§20 Abs. 6 Satz 1 EStG: losses from capital income offset only capital
    income, within their statutory category — a termingeschaefte loss leaves
    the aktien and sonstige balances untouched."""
    balances = _balances(
        [
            _event("aktien", "1000"),
            _event("sonstige", "300"),
            _event("termingeschaefte", "-800"),
        ]
    )
    assert balances["aktien"].balance_eur == Decimal("1000")
    assert balances["sonstige"].balance_eur == Decimal("300")
    assert balances["termingeschaefte"].balance_eur == Decimal("-800")


def test_a_share_sale_loss_offsets_only_share_sale_gains():
    """§20 Abs. 6 Satz 4 EStG: losses from the sale of shares may be offset
    only against gains from the sale of shares — a dividend in the sonstige
    pot stays whole while the aktien pot goes negative."""
    balances = _balances(
        [
            _event("aktien", "-500"),
            _event("aktien", "200"),
            _event("sonstige", "400", source="leg:dividend"),
        ]
    )
    assert balances["aktien"].balance_eur == Decimal("-300")
    assert balances["sonstige"].balance_eur == Decimal("400")


def test_a_sonstige_loss_offsets_other_income_in_its_pot_including_dividends():
    """§20 Abs. 6 Satz 1 EStG: within the general pot a loss offsets any
    capital income there — a fund-sale loss against a dividend."""
    balances = _balances(
        [
            _event("sonstige", "-250", source="leg:fund-sale"),
            _event("sonstige", "400", source="leg:dividend"),
        ]
    )
    assert balances["sonstige"].balance_eur == Decimal("150")


def test_a_category_with_no_events_states_a_zero_balance():
    """Every category is tracked at every stage — a year with no
    termingeschaefte still states that pot's line, at zero, so the form
    line can be filled directly."""
    balances = _balances([_event("aktien", "10")])
    assert set(balances) == {"aktien", "sonstige", "termingeschaefte"}
    assert balances["sonstige"].balance_eur == Decimal(0)
    assert balances["termingeschaefte"].balance_eur == Decimal(0)


# --- Teilfreistellung, before the pot ----------------------------------------


def test_the_partial_exemption_is_applied_before_an_event_enters_its_pot():
    """§20 Abs. 1 InvStG: Teilfreistellung exempts a share of the *income* —
    30 % of an equity fund's 1000 € distribution never reaches the pot, so
    700 € nets against the pot's other events."""
    balances = _balances(
        [
            _event("sonstige", "1000", rate="0.30"),
            _event("sonstige", "-100"),
        ]
    )
    assert balances["sonstige"].balance_eur == Decimal("600")


def test_the_partial_exemption_applies_to_a_loss_symmetrically():
    """§21 InvStG: the exemption applies to losses alike — a 1000 € equity-
    fund loss enters its pot as 700 €."""
    balances = _balances([_event("sonstige", "-1000", rate="0.30")])
    assert balances["sonstige"].balance_eur == Decimal("-700")


# --- The per-year loss cap, configuration never a constant -------------------


def test_a_loss_beyond_the_configured_cap_is_held_back():
    """§20 Abs. 6 Satz 5 EStG (as configured for the year): a category's
    recognised loss is capped, the excess stated beside the balance — what
    becomes carryforward when ticket 27 arrives."""
    balances = _balances(
        [_event("termingeschaefte", "-25000")],
        caps={"termingeschaefte": Decimal("20000")},
    )
    pot = balances["termingeschaefte"]
    assert pot.net_eur == Decimal("-25000")
    assert pot.cap_eur == Decimal("20000")
    assert pot.balance_eur == Decimal("-20000")
    assert pot.loss_beyond_cap_eur == Decimal("5000")


def test_a_loss_exactly_at_the_cap_passes_whole():
    """§20 Abs. 6 Satz 5 EStG boundary: the cap is an amount losses may
    reach — a loss exactly at it is recognised in full, nothing held back."""
    balances = _balances(
        [_event("termingeschaefte", "-20000")],
        caps={"termingeschaefte": Decimal("20000")},
    )
    pot = balances["termingeschaefte"]
    assert pot.balance_eur == Decimal("-20000")
    assert pot.loss_beyond_cap_eur == Decimal(0)


def test_a_category_with_no_cap_configured_is_uncapped():
    """JStG 2024 struck the §20 Abs. 6 Satz 5/6 caps: an absent cap means
    uncapped, never unknown — the whole loss is recognised."""
    balances = _balances([_event("termingeschaefte", "-1000000")], caps={})
    pot = balances["termingeschaefte"]
    assert pot.cap_eur is None
    assert pot.balance_eur == Decimal("-1000000")
    assert pot.loss_beyond_cap_eur == Decimal(0)


def test_the_cap_never_touches_a_positive_balance():
    """The cap bounds recognised *losses* — a gain above the cap's figure
    passes untouched."""
    balances = _balances(
        [_event("termingeschaefte", "50000")],
        caps={"termingeschaefte": Decimal("20000")},
    )
    assert balances["termingeschaefte"].balance_eur == Decimal("50000")
    assert balances["termingeschaefte"].loss_beyond_cap_eur == Decimal(0)


def test_each_category_wears_its_own_cap():
    """The caps are per category and per year: capping termingeschaefte
    leaves an aktien loss of the same size whole."""
    balances = _balances(
        [_event("aktien", "-25000"), _event("termingeschaefte", "-25000")],
        caps={"termingeschaefte": Decimal("20000")},
    )
    assert balances["aktien"].balance_eur == Decimal("-25000")
    assert balances["termingeschaefte"].balance_eur == Decimal("-20000")


# --- Netting to exactly zero -------------------------------------------------


def test_a_pot_netting_to_exactly_zero_states_zero():
    """A gain and a loss of equal size leave the pot at exactly zero — a
    stated figure, not an absence."""
    balances = _balances(
        [_event("sonstige", "1234.56"), _event("sonstige", "-1234.56")],
        caps={"sonstige": Decimal("20000")},
    )
    pot = balances["sonstige"]
    assert pot.net_eur == Decimal(0)
    assert pot.balance_eur == Decimal(0)
    assert pot.loss_beyond_cap_eur == Decimal(0)


# --- The Tax Year boundary ---------------------------------------------------


def test_an_event_on_each_side_of_the_year_boundary_lands_in_its_own_year():
    """Income belongs to the year of its Europe/Berlin date (§11 EStG, the
    clock services/fx.event_date already keeps): New Year's Eve counts, the
    next morning is the next year's."""
    events = [
        _event("sonstige", "100", on=date(2025, 12, 31), source="leg:eve"),
        _event("sonstige", "40", on=date(2026, 1, 1), source="leg:morning"),
    ]
    assert _balances(events, year=2025)["sonstige"].balance_eur == Decimal("100")
    assert _balances(events, year=2026)["sonstige"].balance_eur == Decimal("40")


# --- Traceability ------------------------------------------------------------


def test_every_balance_names_the_events_that_produced_it():
    """Every output figure is traceable: a pot lists each event it counted,
    wearing its source reference and the amount it entered with — the
    Teilfreistellung already applied."""
    balances = _balances(
        [
            _event("sonstige", "1000", rate="0.30", source="leg:7"),
            _event("sonstige", "-100", source="leg:9"),
            _event("aktien", "50", source="leg:11"),
        ]
    )
    entries = balances["sonstige"].entries
    assert [(entry.event.source, entry.counted_eur) for entry in entries] == [
        ("leg:7", Decimal("700")),
        ("leg:9", Decimal("-100")),
    ]
    assert [entry.event.source for entry in balances["aktien"].entries] == ["leg:11"]
    assert balances["termingeschaefte"].entries == ()


def test_an_event_with_an_unknown_category_is_refused():
    """The three categories are the whole vocabulary — an event claiming
    another is a programming error, refused loudly rather than dropped."""
    with pytest.raises(ValueError, match="futures"):
        _balances([_event("futures", "100")])


# --- The producer: the ledger's §20-typed income, reduced to events ----------


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


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _btc(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _income(db, account, instrument, *, type, quantity, occurred_at):
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


def _pots(report):
    return {balance.category: balance for balance in report.balances}


def test_a_euro_dividend_becomes_a_sonstige_event(db):
    """§20 Abs. 1 Nr. 1 EStG: a dividend is capital income in the general
    pot — reduced to one Section 20 Event carrying the ledger leg that
    produced it, gross by the numéraire's identity, withholding empty until
    ticket 43 states what was taken at source."""
    account, eur = _account(db), _eur(db)
    _income(db, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    report = section20.year_report(db, FakeReferenceRateSource(), year=2031)

    assert report.year == 2031
    assert report.awaiting_valuation == ()
    assert report.excluded == ()
    pots = _pots(report)
    assert pots["sonstige"].balance_eur == Decimal("500")
    (entry,) = pots["sonstige"].entries
    event = entry.event
    assert event.category == "sonstige"
    assert event.gross_eur == Decimal("500")
    assert event.exemption_rate == Decimal(0)
    assert event.german_withholding == section20.NO_GERMAN_WITHHOLDING
    assert event.foreign_withholding is None
    assert event.date == date(2031, 3, 14)
    assert event.source.startswith("leg:")


def test_dividends_distributions_and_interest_all_reach_the_sonstige_pot(db):
    """§20 Abs. 1 Nr. 1 und 7 EStG: dividends, fund distributions and
    interest are all general-pot capital income — only share *sales* belong
    to the aktien pot (§20 Abs. 6 Satz 4), and futures to their own."""
    account, eur = _account(db), _eur(db)
    for type, quantity in (("dividend", "100"), ("distribution", "40"), ("interest", "2.50")):
        _income(db, account, eur, type=type, quantity=quantity, occurred_at=RECEIVED_2031)

    pots = _pots(section20.year_report(db, FakeReferenceRateSource(), year=2031))

    assert pots["sonstige"].balance_eur == Decimal("142.50")
    assert pots["aktien"].balance_eur == Decimal(0)
    assert pots["termingeschaefte"].balance_eur == Decimal(0)


def test_the_caps_are_read_from_the_year_s_configuration(store):
    """§20 Abs. 6 Satz 5 EStG as configuration (ticket 09): the year's cap
    reaches the engine from the store, never from a constant — and the two
    unconfigured pots stay uncapped."""
    statutory.upsert_value(
        store, year=2031, key="loss_cap_sonstige", value=Decimal("20000"), source="a cited source"
    )
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="interest", quantity="1", occurred_at=RECEIVED_2031)

    pots = _pots(section20.year_report(store, FakeReferenceRateSource(), year=2031))

    assert pots["sonstige"].cap_eur == Decimal("20000")
    assert pots["aktien"].cap_eur is None
    assert pots["termingeschaefte"].cap_eur is None


def test_income_is_bucketed_by_the_berlin_local_date_of_its_instant(db):
    """The Tax Year boundary at the producer: an instant late on New Year's
    Eve UTC is already the next year in Europe/Berlin — the clock every tax
    figure keeps (services/fx.event_date)."""
    account, eur = _account(db), _eur(db)
    eve_utc = datetime(2031, 12, 31, 23, 30, tzinfo=UTC)
    _income(db, account, eur, type="interest", quantity="9", occurred_at=eve_utc)

    assert _pots(section20.year_report(db, FakeReferenceRateSource(), year=2031))[
        "sonstige"
    ].balance_eur == Decimal(0)
    assert _pots(section20.year_report(db, FakeReferenceRateSource(), year=2032))[
        "sonstige"
    ].balance_eur == Decimal("9")


def test_income_awaiting_a_crypto_price_leaves_the_year_unstated(db):
    """A value the reference-rate universe cannot state waits for a crypto
    price (ticket 18): while any §20 event awaits valuation the year states
    no balances — netting around a missing member could flip a pot — and
    names the legs it waits on."""
    account, btc = _account(db), _btc(db)
    _eur(db)
    _keep(db, btc, account)
    _income(db, account, btc, type="distribution", quantity="0.1", occurred_at=RECEIVED_2031)

    report = section20.year_report(db, FakeReferenceRateSource(), year=2031)

    assert report.balances is None
    assert len(report.awaiting_valuation) == 1


def test_a_non_kept_instrument_s_income_is_excluded_by_name(db):
    """Income enters exactly when its in-leg mints a lot (services/stances):
    an unacknowledged position waits visibly in the inbox, and the report
    names what it kept out — a stated balance can never silently hide a
    receipt awaiting a decision."""
    account, btc = _account(db), _btc(db)
    _eur(db)
    _income(db, account, btc, type="distribution", quantity="0.1", occurred_at=RECEIVED_2031)

    report = section20.year_report(db, FakeReferenceRateSource(), year=2031)

    (kept_out,) = report.excluded
    assert kept_out.type == "distribution"
    assert kept_out.stance == "unacknowledged"
    assert _pots(report)["sonstige"].balance_eur == Decimal(0)
