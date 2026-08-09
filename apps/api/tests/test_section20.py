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

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.repositories import instruments, platforms, stances, statutory, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import section20
from open_leprechaun.services.statutory import StatutoryValueUnsetError

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


# --- Carryforward across years, inside its own category (ticket 27) ---------


def _carried(events, *, year, carryforward_in=None, openings=None, caps=None):
    """One year rolled forward, keyed by category, for assertions by name —
    the events re-dated into the year, so a test reads amounts, not dates."""
    events = [replace(event, date=date(year, 6, 15)) for event in events]
    balances = section20.net(events, year=year, caps=caps or {})
    return {
        carried.category: carried
        for carried in section20.carry(
            balances, year=year, carryforward_in=carryforward_in, openings=openings
        )
    }


def _layer(origin_year, amount, *, opening=False):
    return section20.CarryforwardLayer(
        origin_year=origin_year, amount_eur=Decimal(amount), opening=opening
    )


def test_a_loss_year_produces_a_carryforward_stating_amount_and_category():
    """§20 Abs. 6 Satz 2 und 3 EStG: a loss the year could not offset carries
    forward to reduce the same category's later income — the year states the
    amount and the category it stays inside."""
    carried = _carried([_event("sonstige", "-300")], year=2025)

    pot = carried["sonstige"]
    assert pot.produced_eur == Decimal("300")
    assert pot.surviving_eur == Decimal(0)
    assert pot.carryforward_out == (_layer(2025, "300"),)
    assert carried["aktien"].produced_eur == Decimal(0)


def test_a_gain_year_consumes_the_carryforward_naming_the_year_it_came_from():
    """§20 Abs. 6 Satz 2 EStG: a later gain is reduced by the carried loss
    before anything else — and the consumption names the origin year, so the
    figure is traceable to the year that established it."""
    carried = _carried(
        [_event("sonstige", "500")],
        year=2026,
        carryforward_in={"sonstige": (_layer(2025, "300"),)},
    )

    pot = carried["sonstige"]
    assert pot.consumed == (_layer(2025, "300"),)
    assert pot.surviving_eur == Decimal("200")
    assert pot.carryforward_out == ()


def test_a_carryforward_never_crosses_categories():
    """§20 Abs. 6 Satz 4 EStG: an aktien loss carried forward shelters only
    aktien gains — a sonstige gain beside it stays whole, and the aktien
    carryforward stays put."""
    carried = _carried(
        [_event("sonstige", "500")],
        year=2026,
        carryforward_in={"aktien": (_layer(2025, "300"),)},
    )

    assert carried["sonstige"].consumed == ()
    assert carried["sonstige"].surviving_eur == Decimal("500")
    assert carried["aktien"].carryforward_out == (_layer(2025, "300"),)


def test_consumption_is_oldest_first_and_a_partial_layer_keeps_its_origin():
    """The carryforward is one pot per category in law; the layers exist so a
    consumption can name its origin — eaten oldest first, a partly consumed
    layer keeping its year."""
    carried = _carried(
        [_event("sonstige", "150")],
        year=2027,
        carryforward_in={"sonstige": (_layer(2025, "100"), _layer(2026, "200"))},
    )

    pot = carried["sonstige"]
    assert pot.consumed == (_layer(2025, "100"), _layer(2026, "50"))
    assert pot.carryforward_out == (_layer(2026, "150"),)


def test_a_carryforward_exactly_exhausted_leaves_an_empty_pot():
    """Boundary: a gain exactly the size of the carried loss consumes it to
    the cent — nothing survives and nothing carries on."""
    carried = _carried(
        [_event("sonstige", "300")],
        year=2026,
        carryforward_in={"sonstige": (_layer(2025, "300"),)},
    )

    pot = carried["sonstige"]
    assert pot.consumed == (_layer(2025, "300"),)
    assert pot.surviving_eur == Decimal(0)
    assert pot.carryforward_out == ()


def test_a_capped_loss_carries_forward_in_full():
    """§20 Abs. 6 Satz 5 EStG (as configured): the cap bounds what a year may
    offset, not what carries — the recognised loss found nothing to offset and
    the excess was held back, so the whole loss travels."""
    carried = _carried(
        [_event("termingeschaefte", "-25000")],
        year=2025,
        caps={"termingeschaefte": Decimal("20000")},
    )

    assert carried["termingeschaefte"].produced_eur == Decimal("25000")
    assert carried["termingeschaefte"].carryforward_out == (_layer(2025, "25000"),)


def test_a_configured_cap_bounds_what_a_gain_year_may_consume():
    """§20 Abs. 6 Satz 5 EStG (as configured), second half: carried losses
    reduce a following year's gains only up to the year's cap — the rest
    keeps waiting."""
    carried = _carried(
        [_event("termingeschaefte", "25000")],
        year=2026,
        carryforward_in={"termingeschaefte": (_layer(2025, "30000"),)},
        caps={"termingeschaefte": Decimal("20000")},
    )

    pot = carried["termingeschaefte"]
    assert pot.consumed == (_layer(2025, "20000"),)
    assert pot.surviving_eur == Decimal("5000")
    assert pot.carryforward_out == (_layer(2025, "10000"),)


def test_an_opening_carryforward_predating_the_ledger_is_consumed_first():
    """A loss established by an assessment before the ledger existed still
    shelters income here (ADR-0013): the opening balance enters as the oldest
    layer, wearing the year it was entered for."""
    carried = _carried(
        [_event("aktien", "250")],
        year=2024,
        openings={"aktien": Decimal("400")},
    )

    pot = carried["aktien"]
    assert pot.carryforward_in == (_layer(2024, "400", opening=True),)
    assert pot.consumed == (_layer(2024, "250", opening=True),)
    assert pot.carryforward_out == (_layer(2024, "150", opening=True),)


def test_an_absent_opening_carryforward_means_zero_not_unknown():
    """No opening balance configured is an answer — zero — never a refusal
    to compute."""
    carried = _carried([_event("aktien", "250")], year=2024)

    assert carried["aktien"].carryforward_in == ()
    assert carried["aktien"].surviving_eur == Decimal("250")


# --- The allowance: one deduction across the combined total ------------------


def _assessed(
    carried_by_category,
    *,
    year=2025,
    allowance="1000",
    used_at_source="0",
    flat_rate="0.25",
    soli="0.055",
    church=None,
):
    return section20.assess(
        tuple(carried_by_category.values()),
        year=year,
        allowance_eur=Decimal(allowance),
        allowance_used_at_source_eur=Decimal(used_at_source),
        flat_rate=Decimal(flat_rate),
        solidarity_surcharge_rate=Decimal(soli),
        church_tax_rate=Decimal(church) if church is not None else None,
    )


def test_surviving_categories_are_summed_after_offsetting_and_carryforward():
    """The combined total is what survives each pot — a pot still negative
    after its own netting contributes nothing and keeps its loss to itself."""
    carried = _carried(
        [_event("aktien", "800"), _event("sonstige", "700"), _event("termingeschaefte", "-400")],
        year=2025,
    )

    assessment = _assessed(carried)

    assert assessment.combined_eur == Decimal("1500")
    assert assessment.taxable_eur == Decimal("500")


def test_the_allowance_is_a_deduction_never_a_threshold():
    """§20 Abs. 9 Satz 1 EStG: the Sparerpauschbetrag is subtracted — income
    above it is taxed only on the excess, unlike the §22/§23 Freigrenzen."""
    carried = _carried([_event("sonstige", "1500")], year=2025)

    assessment = _assessed(carried, allowance="1000")

    assert assessment.allowance_applied_eur == Decimal("1000")
    assert assessment.taxable_eur == Decimal("500")


def test_the_allowance_is_applied_once_across_the_combined_total_never_per_source():
    """§20 Abs. 9 EStG: one allowance for the year, across everything that
    survives — two pots of 800 and 700 leave 500 taxable, where a per-source
    allowance would wrongly leave nothing."""
    carried = _carried([_event("aktien", "800"), _event("sonstige", "700")], year=2025)

    assessment = _assessed(carried, allowance="1000")

    assert assessment.taxable_eur == Decimal("500")


def test_the_allowance_cannot_push_the_income_below_zero():
    """§20 Abs. 9 Satz 4 EStG: the deduction stops at zero — it never
    manufactures a loss."""
    carried = _carried([_event("sonstige", "300")], year=2025)

    assessment = _assessed(carried, allowance="1000")

    assert assessment.allowance_applied_eur == Decimal("300")
    assert assessment.taxable_eur == Decimal(0)


def test_the_allowance_exactly_consumed_leaves_zero_taxable():
    """Boundary: income exactly the allowance — fully deducted, zero taxable,
    zero tax."""
    carried = _carried([_event("sonstige", "1000")], year=2025)

    assessment = _assessed(carried, allowance="1000")

    assert assessment.allowance_applied_eur == Decimal("1000")
    assert assessment.taxable_eur == Decimal(0)
    assert assessment.tax.total_eur == Decimal(0)


def test_allowance_consumed_at_source_is_deducted_before_the_app_claims_any():
    """§44a EStG: what a Freistellungsauftrag already exempted at source is
    gone — the assessment may claim only the remainder, so the two together
    can never exceed the year's allowance."""
    carried = _carried([_event("sonstige", "1500")], year=2025)

    assessment = _assessed(carried, allowance="1000", used_at_source="600")

    assert assessment.allowance_used_at_source_eur == Decimal("600")
    assert assessment.allowance_applied_eur == Decimal("400")
    assert assessment.taxable_eur == Decimal("1100")


def test_an_allowance_fully_consumed_at_source_leaves_nothing_to_claim():
    """Boundary: exemption orders already used the whole allowance — the
    assessment deducts nothing further."""
    carried = _carried([_event("sonstige", "1500")], year=2025)

    assessment = _assessed(carried, allowance="1000", used_at_source="1000")

    assert assessment.allowance_applied_eur == Decimal(0)
    assert assessment.taxable_eur == Decimal("1500")


def test_a_year_whose_losses_exceed_everything_available_owes_nothing_and_carries_all():
    """Boundary: losses beyond every gain and the whole allowance — nothing
    taxable, no tax, the allowance untouched (it never carries), and the full
    loss travels into the category's next year."""
    carried = _carried(
        [_event("sonstige", "200"), _event("aktien", "-5000")],
        year=2025,
        carryforward_in={"aktien": (_layer(2024, "1000"),)},
    )

    assessment = _assessed(carried, allowance="1000")

    assert assessment.combined_eur == Decimal("200")
    assert assessment.allowance_applied_eur == Decimal("200")
    assert assessment.taxable_eur == Decimal(0)
    assert assessment.tax.total_eur == Decimal(0)
    aktien = {pot.category: pot for pot in assessment.categories}["aktien"]
    assert aktien.carryforward_out == (_layer(2024, "1000"), _layer(2025, "5000"))


# --- The rate: flat, solidarity surcharge, church tax exactly ----------------


def test_the_flat_rate_and_the_solidarity_surcharge_produce_the_return_figure():
    """§32d Abs. 1 Satz 1 EStG und §4 Satz 1 SolzG 1995: 25 % on the taxable
    amount, 5.5 % of that tax on top — 2000 € taxable owes 500 € and 27.50 €."""
    carried = _carried([_event("sonstige", "3000")], year=2025)

    assessment = _assessed(carried, allowance="1000")

    assert assessment.tax.income_tax_eur == Decimal("500")
    assert assessment.tax.solidarity_surcharge_eur == Decimal("27.50")
    assert assessment.tax.church_tax_eur == Decimal(0)
    assert assessment.tax.total_eur == Decimal("527.50")


def test_church_tax_uses_the_exact_formula_with_its_deduction_effect():
    """§32d Abs. 1 Satz 3 bis 5 EStG: church tax is deductible inside the
    flat scheme, so the income tax is e / (4 + k), not 25 % — 1000 € taxable
    at 9 % church tax owes 244.50 €, never the approximation 250 €."""
    carried = _carried([_event("sonstige", "2000")], year=2025)

    assessment = _assessed(carried, allowance="1000", church="0.09")

    assert assessment.tax.income_tax_eur == Decimal("244.50")
    assert assessment.tax.church_tax_eur == Decimal("22.00")
    assert assessment.tax.solidarity_surcharge_eur == Decimal("13.45")
    assert assessment.tax.total_eur == Decimal("279.95")


def test_the_result_notes_the_personal_rate_comparison_without_computing_it():
    """§32d Abs. 6 EStG (ADR-0007): the Günstigerprüfung may yield less tax —
    the assessment says so and deliberately computes nothing."""
    carried = _carried([_event("sonstige", "1500")], year=2025)

    assessment = _assessed(carried)

    assert "32d Abs. 6" in assessment.personal_rate_note
    assert "Günstigerprüfung" in assessment.personal_rate_note


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


def _statutes(store, *, year=2031):
    """The values the §20 assessment reads for a year no migration seeds:
    the single-filing allowance and the two rates every year requires."""
    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="a test value"
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


def test_a_euro_dividend_becomes_a_sonstige_event(store):
    """§20 Abs. 1 Nr. 1 EStG: a dividend is capital income in the general
    pot — reduced to one Section 20 Event carrying the ledger leg that
    produced it, gross by the numéraire's identity, withholding empty until
    ticket 43 states what was taken at source."""
    _statutes(store)
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

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


def test_dividends_distributions_and_interest_all_reach_the_sonstige_pot(store):
    """§20 Abs. 1 Nr. 1 und 7 EStG: dividends, fund distributions and
    interest are all general-pot capital income — only share *sales* belong
    to the aktien pot (§20 Abs. 6 Satz 4), and futures to their own."""
    _statutes(store)
    account, eur = _account(store), _eur(store)
    for type, quantity in (("dividend", "100"), ("distribution", "40"), ("interest", "2.50")):
        _income(store, account, eur, type=type, quantity=quantity, occurred_at=RECEIVED_2031)

    pots = _pots(section20.year_report(store, FakeReferenceRateSource(), year=2031))

    assert pots["sonstige"].balance_eur == Decimal("142.50")
    assert pots["aktien"].balance_eur == Decimal(0)
    assert pots["termingeschaefte"].balance_eur == Decimal(0)


def test_the_caps_are_read_from_the_year_s_configuration(store):
    """§20 Abs. 6 Satz 5 EStG as configuration (ticket 09): the year's cap
    reaches the engine from the store, never from a constant — and the two
    unconfigured pots stay uncapped."""
    _statutes(store)
    statutory.upsert_value(
        store, year=2031, key="loss_cap_sonstige", value=Decimal("20000"), source="a cited source"
    )
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="interest", quantity="1", occurred_at=RECEIVED_2031)

    pots = _pots(section20.year_report(store, FakeReferenceRateSource(), year=2031))

    assert pots["sonstige"].cap_eur == Decimal("20000")
    assert pots["aktien"].cap_eur is None
    assert pots["termingeschaefte"].cap_eur is None


def test_income_is_bucketed_by_the_berlin_local_date_of_its_instant(store):
    """The Tax Year boundary at the producer: an instant late on New Year's
    Eve UTC is already the next year in Europe/Berlin — the clock every tax
    figure keeps (services/fx.event_date)."""
    _statutes(store, year=2031)
    _statutes(store, year=2032)
    account, eur = _account(store), _eur(store)
    eve_utc = datetime(2031, 12, 31, 23, 30, tzinfo=UTC)
    _income(store, account, eur, type="interest", quantity="9", occurred_at=eve_utc)

    assert _pots(section20.year_report(store, FakeReferenceRateSource(), year=2031))[
        "sonstige"
    ].balance_eur == Decimal(0)
    assert _pots(section20.year_report(store, FakeReferenceRateSource(), year=2032))[
        "sonstige"
    ].balance_eur == Decimal("9")


def test_income_awaiting_a_crypto_price_leaves_the_year_unstated(store):
    """A value the reference-rate universe cannot state waits for a crypto
    price (ticket 18): while any §20 event awaits valuation the year states
    no balances and no assessment — netting around a missing member could
    flip a pot — and names the legs it waits on."""
    _statutes(store)
    account, btc = _account(store), _btc(store)
    _eur(store)
    _keep(store, btc, account)
    _income(store, account, btc, type="distribution", quantity="0.1", occurred_at=RECEIVED_2031)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.balances is None
    assert report.assessment is None
    assert len(report.awaiting_valuation) == 1


def test_a_non_kept_instrument_s_income_is_excluded_by_name(store):
    """Income enters exactly when its in-leg mints a lot (services/stances):
    an unacknowledged position waits visibly in the inbox, and the report
    names what it kept out — a stated balance can never silently hide a
    receipt awaiting a decision."""
    _statutes(store)
    account, btc = _account(store), _btc(store)
    _eur(store)
    _income(store, account, btc, type="distribution", quantity="0.1", occurred_at=RECEIVED_2031)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    (kept_out,) = report.excluded
    assert kept_out.type == "distribution"
    assert kept_out.stance == "unacknowledged"
    assert _pots(report)["sonstige"].balance_eur == Decimal(0)


# --- The producer, second half: configuration to assessment (ticket 27) ------


def test_the_year_report_carries_the_assessment_from_configured_values(store):
    """The whole chain from store to return figure: a 500 € dividend under
    the configured 1000 € allowance leaves nothing taxable — the allowance a
    deduction read per year from configuration, never a constant."""
    _statutes(store)
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    assessment = section20.year_report(store, FakeReferenceRateSource(), year=2031).assessment

    assert assessment is not None
    assert assessment.combined_eur == Decimal("500")
    assert assessment.allowance_eur == Decimal("1000")
    assert assessment.allowance_used_at_source_eur == Decimal(0)
    assert assessment.allowance_applied_eur == Decimal("500")
    assert assessment.taxable_eur == Decimal(0)
    assert assessment.tax.total_eur == Decimal(0)
    assert "Günstigerprüfung" in assessment.personal_rate_note


def test_an_opening_carryforward_rolls_across_years_to_shelter_later_income(store):
    """§20 Abs. 6 Satz 2 und 3 EStG across real years: a carryforward entered
    for an earlier year — from an assessment predating the ledger — walks
    forward inside its category and reduces this year's income first, the
    consumption naming the year it was entered for."""
    _statutes(store)
    statutory.upsert_value(
        store,
        year=2030,
        key="opening_carryforward_sonstige",
        value=Decimal("300"),
        source="Verlustfeststellungsbescheid",
    )
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    assessment = section20.year_report(store, FakeReferenceRateSource(), year=2031).assessment

    assert assessment is not None
    sonstige = {pot.category: pot for pot in assessment.categories}["sonstige"]
    assert sonstige.consumed == (
        section20.CarryforwardLayer(origin_year=2030, amount_eur=Decimal("300"), opening=True),
    )
    assert assessment.combined_eur == Decimal("200")


def test_the_church_tax_election_selects_the_exact_formula(store):
    """§32d Abs. 1 Satz 3 bis 5 EStG through the election: with church tax
    elected the year's rate is read from configuration and the income tax is
    taxable / (4 + k) — the deduction effect exact, never 25 % approximated."""
    _statutes(store)
    statutory.upsert_value(
        store,
        year=2031,
        key="church_tax_rate_other_laender",
        value=Decimal("0.09"),
        source="KiStG der übrigen Länder",
    )
    statutory.set_election(store, filing_status="single", church_tax="other_laender")
    try:
        account, eur = _account(store), _eur(store)
        _income(store, account, eur, type="dividend", quantity="2000", occurred_at=RECEIVED_2031)

        assessment = section20.year_report(store, FakeReferenceRateSource(), year=2031).assessment
    finally:
        statutory.set_election(store, filing_status="single", church_tax="none")

    assert assessment is not None
    assert assessment.taxable_eur == Decimal("1000")
    assert assessment.tax.income_tax_eur == Decimal("244.50")
    assert assessment.tax.church_tax_eur == Decimal("22.00")


def test_a_prior_year_event_awaiting_valuation_blocks_the_chained_year(store):
    """Carryforward makes earlier years inputs to this one: while a prior
    year's event awaits a crypto price, this year states no balances and no
    assessment — the unvalued loss could change every carryforward after it —
    and names the leg it waits on."""
    _statutes(store)
    account, btc = _account(store), _btc(store)
    eur = _eur(store)
    _keep(store, btc, account)
    prior = datetime(2030, 3, 14, 12, 0, tzinfo=UTC)
    _income(store, account, btc, type="distribution", quantity="0.1", occurred_at=prior)
    _income(store, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.balances is None
    assert report.assessment is None
    assert len(report.awaiting_valuation) == 1


def test_a_prior_year_s_exclusion_is_not_relisted_on_this_year(store):
    """A stance-excluded receipt is named by its own year's report; a later
    year's chain skips it without repeating the naming — this year's excluded
    list stays its own."""
    _statutes(store)
    account, btc = _account(store), _btc(store)
    eur = _eur(store)
    prior = datetime(2030, 3, 14, 12, 0, tzinfo=UTC)
    _income(store, account, btc, type="distribution", quantity="0.1", occurred_at=prior)
    _income(store, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.excluded == ()
    assert report.assessment is not None
    assert report.assessment.combined_eur == Decimal("500")


def test_a_year_missing_the_allowance_refuses_by_name(store):
    """All statutory values come from per-year configuration: a year whose
    Sparerpauschbetrag is unset refuses by name and statute rather than
    assuming one."""
    account, eur = _account(store), _eur(store)
    _income(store, account, eur, type="dividend", quantity="500", occurred_at=RECEIVED_2031)

    with pytest.raises(StatutoryValueUnsetError, match="saver_allowance_single"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)
