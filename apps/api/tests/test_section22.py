"""§22 EStG Sonstige Einkünfte — the income engine (ticket 22). Staking
rewards, lending interest, mining and qualifying airdrops are valued at
market value on receipt — the same event minting a Tax Lot at that basis —
and pool under the annual §22 Nr. 3 Satz 2 Freigrenze, read per year from
the statutory store and applied as *weniger als*.

The seams are the engine's one public read — `section22.year_report`, driven
over real Postgres with the ledger built through the repositories and rates
through a fake of the reference-rate port — and its named refusals.
"""

from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import instruments, platforms, stances, statutory, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import lots, section22, section23
from open_leprechaun.services import stances as stances_service

RECEIVED = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)
SOLD = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)


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


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _eurc(db):
    """A euro stablecoin: its peg values it by identity, so an amount is its
    own EUR market value — boundary tests need no rate rows."""
    return instruments.create_crypto_token(
        db,
        symbol="EURC",
        name="Euro Coin",
        chain="ethereum",
        contract_address="0x1abaea1f7c830bd89acc67ec4af516284b1bc33c",
        pegged_currency="EUR",
    )


def _usdt(db):
    return instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )


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


# --- Valued at market value on receipt, minting a lot at that basis ---------


def test_income_is_valued_at_market_value_on_receipt(db):
    """§22 Nr. 3 EStG: a Leistung's income is the market value of what was
    received, by the reference rate of the event date (ADR-0017) — and the
    event is named with the type that classified it."""
    account, usdt = _account(db), _usdt(db)
    _eur(db)
    _keep(db, usdt, account)
    _income(db, account, usdt, type="lending_interest", quantity="1000", occurred_at=RECEIVED)
    source = FakeReferenceRateSource(
        [ReferenceRate(currency="USD", rate_date=RECEIVED.date(), rate=Decimal("1.25"))]
    )

    report = section22.year_report(db, source, year=2025)

    (event,) = report.incomes
    assert event.type == "lending_interest"
    assert event.account_id == account
    assert event.instrument_id == usdt
    assert event.received_at == RECEIVED
    assert event.tax_year == 2025
    assert event.quantity == Decimal("1000")
    assert event.market_value_eur == Decimal("800")
    assert report.total_income_eur == Decimal("800")
    assert report.awaiting_valuation == ()


def test_income_simultaneously_mints_a_lot_at_that_basis(db):
    """One event, one valuation rule: the reward's in-leg mints a Tax Lot
    marked market_value at the receipt instant, and the disposal engine (21)
    states its basis by the same rule that valued the income — income and
    cost basis agree to the cent."""
    account, usdt = _account(db), _usdt(db)
    eur = _eur(db)
    _keep(db, usdt, account)
    _income(db, account, usdt, type="staking_reward", quantity="1000", occurred_at=RECEIVED)
    source = FakeReferenceRateSource(
        [ReferenceRate(currency="USD", rate_date=RECEIVED.date(), rate=Decimal("1.25"))]
    )

    income = section22.year_report(db, source, year=2025)

    (lot,) = lots.fresh_lots(db)
    assert lot.basis_source == lots.MARKET_VALUE
    assert lot.acquired_at == RECEIVED
    assert lot.quantity == Decimal("1000")

    sold = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=SOLD,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=usdt, role="out", quantity=Decimal("1000")),
            Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("810")),
        ],
    )
    assert isinstance(sold, int)
    disposal_report = section23.year_report(db, source, year=2025)

    (disposal,) = disposal_report.disposals
    (consumption,) = disposal.consumptions
    assert consumption.basis_source == "market_value"
    assert consumption.basis_eur == income.total_income_eur == Decimal("800")
    assert consumption.gain_eur == Decimal("10")


# --- One annual limit over the whole pool -----------------------------------


def test_all_qualifying_income_pools_under_one_limit(db):
    """Staking, lending, mining and a qualifying airdrop pool together —
    one bucket, one annual Freigrenze — and the result names every event it
    pooled, each wearing its own type."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _keep(db, eurc, account)
    for offset, (type_, quantity) in enumerate(
        [
            ("staking_reward", "100"),
            ("lending_interest", "60"),
            ("mining_reward", "50"),
            ("airdrop", "46"),
        ]
    ):
        _income(
            db,
            account,
            eurc,
            type=type_,
            quantity=quantity,
            occurred_at=RECEIVED.replace(day=1 + offset),
        )

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    assert [event.type for event in report.incomes] == [
        "staking_reward",
        "lending_interest",
        "mining_reward",
        "airdrop",
    ]
    assert report.total_income_eur == Decimal("256")
    assert report.freigrenze.tax_free is False
    assert report.freigrenze.taxable_income_eur == Decimal("256")


def test_income_below_the_limit_is_entirely_free_with_headroom_stated(db):
    """§22 Nr. 3 Satz 2 EStG: income of less than the limit is not taxable —
    one cent below leaves the whole amount free, with the headroom stated."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _keep(db, eurc, account)
    _income(db, account, eurc, type="staking_reward", quantity="255.99", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    verdict = report.freigrenze
    assert verdict.limit_eur == Decimal("256")
    assert verdict.total_income_eur == Decimal("255.99")
    assert verdict.tax_free is True
    assert verdict.taxable_income_eur == Decimal("0")
    assert verdict.headroom_eur == Decimal("0.01")
    assert verdict.overshoot_eur is None


def test_income_exactly_at_the_threshold_is_already_fully_taxable(db):
    """The statute says *weniger als*: exactly the threshold is not less than
    it, so the full amount is taxable — not just the excess — and the
    overshoot is stated as zero."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _keep(db, eurc, account)
    _income(db, account, eurc, type="staking_reward", quantity="256", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    verdict = report.freigrenze
    assert verdict.tax_free is False
    assert verdict.taxable_income_eur == Decimal("256")
    assert verdict.overshoot_eur == Decimal("0")
    assert verdict.headroom_eur is None


def test_income_just_above_the_limit_is_entirely_taxable(db):
    """One cent above the Freigrenze taxes the whole pool."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _keep(db, eurc, account)
    _income(db, account, eurc, type="mining_reward", quantity="256.01", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    verdict = report.freigrenze
    assert verdict.tax_free is False
    assert verdict.taxable_income_eur == Decimal("256.01")
    assert verdict.overshoot_eur == Decimal("0.01")


def test_the_limit_is_the_years_own_configured_value(db):
    """A future legislature moves the Freigrenze by an UPDATE, not a code
    change: a year configured to 300 € frees the 310 € the seeded years
    would have taxed... and taxes it here."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    statutory.upsert_value(
        db,
        year=2031,
        key="other_income_exemption_limit",
        value=Decimal("300"),
        source="a future amendment",
    )
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _keep(db, eurc, account)
    _income(
        db,
        account,
        eurc,
        type="staking_reward",
        quantity="310",
        occurred_at=datetime(2031, 3, 14, 12, 0, tzinfo=UTC),
    )

    report = section22.year_report(db, FakeReferenceRateSource(), year=2031)

    verdict = report.freigrenze
    assert verdict.limit_eur == Decimal("300")
    assert verdict.tax_free is False
    assert verdict.taxable_income_eur == Decimal("310")
    assert verdict.overshoot_eur == Decimal("10")


def test_a_year_without_its_limit_refuses_to_compute(db):
    """The Freigrenze is per-year configuration (ticket 09); a year with no
    value set is refused by name, never defaulted."""
    with pytest.raises(section22.StatutoryValueUnsetError, match="2019"):
        section22.year_report(db, FakeReferenceRateSource(), year=2019)


def test_the_result_states_a_taxable_amount_never_a_tax_owed(db):
    """ADR-0007: Sonstige Einkünfte are taxed at the Admin's marginal rate,
    which the ledger cannot know — the verdict's whole vocabulary is amounts,
    and the taxable amount is the pool itself, never a euro of tax."""
    field_names = {field.name for field in fields(section22.FreigrenzeVerdict)}
    assert "taxable_income_eur" in field_names
    assert all(name == "tax_free" or not name.startswith("tax_") for name in field_names)
    assert not any("rate" in name or "owed" in name for name in field_names)


# --- Classification follows the transaction type ----------------------------


def test_classification_follows_the_transaction_type(db):
    """Only the four §22 types pool: a purchase is not income, a kept
    windfall has no Leistung (BMF letter of 10.05.2022), and §20 capital
    income belongs to its own engine (ticket 26)."""
    account, eurc = _account(db), _eurc(db)
    eur = _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    _keep(db, eurc, account)
    _keep(db, usd, account)
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=RECEIVED,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=eurc, role="in", quantity=Decimal("500")),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("500")),
        ],
    )
    assert isinstance(created, int)
    _income(db, account, eurc, type="windfall", quantity="400", occurred_at=SOLD)
    _income(db, account, usd, type="interest", quantity="300", occurred_at=SOLD)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    assert report.incomes == ()
    assert report.total_income_eur == Decimal("0")
    assert report.freigrenze.tax_free is True


def test_numeraire_income_is_its_own_value(db):
    """Income paid in the numéraire needs no valuation and no stance — the
    amount is the market value, pooled like any other Leistung."""
    account = _account(db)
    eur = _eur(db)
    _income(db, account, eur, type="lending_interest", quantity="10", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    (event,) = report.incomes
    assert event.market_value_eur == Decimal("10")
    assert report.total_income_eur == Decimal("10")


# --- What stands outside the pool -------------------------------------------


def test_an_unacknowledged_reward_is_excluded_by_name_and_waits_in_the_inbox(db):
    """Deny by default (ADR-0012): an unacknowledged position's reward mints
    no lot and pools no income — the item waits in the inbox, and the report
    names the exclusion so the verdict beside it cannot silently hide it."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _income(db, account, eurc, type="staking_reward", quantity="500", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    assert report.incomes == ()
    assert report.total_income_eur == Decimal("0")
    (left_out,) = report.excluded
    assert left_out.type == "staking_reward"
    assert left_out.instrument_id == eurc
    assert left_out.account_id == account
    assert left_out.stance == "unacknowledged"
    (waiting,) = stances_service.inbox(db)
    assert waiting.instrument_id == eurc
    assert waiting.account_id == account


def test_an_ignored_positions_reward_never_pools(db):
    """Ignored and dangerous positions never enter the cost basis (ADR-0012)
    — their rewards mint nothing and pool nothing, staying ledger entries
    that the report names as excluded, wearing the stance."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    settled = stances.classify(db, eurc, stance="ignored", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    _income(db, account, eurc, type="staking_reward", quantity="500", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    assert report.incomes == ()
    assert report.total_income_eur == Decimal("0")
    (left_out,) = report.excluded
    assert left_out.stance == "ignored"


# --- Valuation by the reference rate ----------------------------------------


def test_income_awaiting_a_crypto_price_blocks_total_and_verdict(db):
    """A market value needing a crypto price (ticket 18) is never guessed:
    the event is named as awaiting valuation, and the year states no total
    and no verdict over the unknown — while the valued event stays listed."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    sol = instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")
    _keep(db, eurc, account)
    _keep(db, sol, account)
    _income(db, account, eurc, type="staking_reward", quantity="100", occurred_at=RECEIVED)
    _income(db, account, sol, type="staking_reward", quantity="0.35", occurred_at=SOLD)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    valued, awaited = report.incomes
    assert valued.market_value_eur == Decimal("100")
    assert awaited.market_value_eur is None
    assert report.awaiting_valuation == (awaited.leg_id,)
    assert report.total_income_eur is None
    assert report.freigrenze is None


def test_only_the_requested_years_income_is_valued(db):
    """Another year's income costs no rate lookup and cannot fail over one:
    a reward in a year with no rates at all leaves the requested year's
    report standing."""
    account, eurc, usdt = _account(db), _eurc(db), _usdt(db)
    _eur(db)
    _keep(db, eurc, account)
    _keep(db, usdt, account)
    _income(
        db,
        account,
        usdt,
        type="lending_interest",
        quantity="100",
        occurred_at=datetime(2024, 3, 14, 12, 0, tzinfo=UTC),
    )
    _income(db, account, eurc, type="staking_reward", quantity="100", occurred_at=RECEIVED)

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    (event,) = report.incomes
    assert event.market_value_eur == Decimal("100")
    assert report.total_income_eur == Decimal("100")


# --- The Tax Year boundary --------------------------------------------------


def test_the_tax_year_follows_the_berlin_local_date(db):
    """A reward in the last UTC hour of December already belongs to the new
    German year (CET is an hour ahead), while one two hours earlier stays in
    the old one — the instant is absolute, only its bucketing is local."""
    account, eurc = _account(db), _eurc(db)
    _eur(db)
    _keep(db, eurc, account)
    _income(
        db,
        account,
        eurc,
        type="staking_reward",
        quantity="40",
        occurred_at=datetime(2025, 12, 31, 22, 30, tzinfo=UTC),
    )
    _income(
        db,
        account,
        eurc,
        type="staking_reward",
        quantity="60",
        occurred_at=datetime(2025, 12, 31, 23, 30, tzinfo=UTC),
    )

    old_year = section22.year_report(db, FakeReferenceRateSource(), year=2025)
    new_year = section22.year_report(db, FakeReferenceRateSource(), year=2026)

    (stayed,) = old_year.incomes
    assert stayed.tax_year == 2025
    assert stayed.market_value_eur == Decimal("40")
    (crossed,) = new_year.incomes
    assert crossed.tax_year == 2026
    assert crossed.market_value_eur == Decimal("60")
