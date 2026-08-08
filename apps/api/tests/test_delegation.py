"""The Staking Delegation marker (ticket 22): informational location per
Account and Instrument, never tax. Committing coins to a validator is not a
disposal, does not touch the Haltefrist, and never enters any engine — and
the ledger has no delegation transaction type, so an import could not record
one as a transaction even by mistake.
"""

from datetime import UTC, datetime
from decimal import Decimal

from open_leprechaun.repositories import instruments, platforms, stances, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import delegation, lots, section22, section23
from open_leprechaun.services.tax_treatment import TAX_CONSEQUENCES
from open_leprechaun.services.transactions import TRANSACTION_TYPES

BOUGHT = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)


class FakeReferenceRateSource:
    def daily_rates(self, currency, start, end):
        return []


def _account(db, platform_name="Phantom", kind="software_wallet", name="Hot wallet"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _sol(db):
    return instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


# --- A marker per Account and Instrument ------------------------------------


def test_a_delegation_is_tracked_per_account_and_instrument(db):
    """The same coin may be delegated in one Account and idle in another, so
    neither the Instrument nor the Account alone can express it — the marker
    names the pair, and removing it means 'no longer delegated'."""
    hot = _account(db)
    vault = _account(db, platform_name="Ledger", kind="cold_storage", name="Vault")
    sol = _sol(db)

    assert delegation.mark(db, instrument_id=sol, account_id=hot, note="Everstake")
    (marker,) = delegation.overview(db)
    assert marker.instrument_id == sol
    assert marker.account_id == hot
    assert marker.symbol == "SOL"
    assert marker.account_name == "Hot wallet"
    assert marker.platform_name == "Phantom"
    assert marker.note == "Everstake"
    assert vault not in [entry.account_id for entry in delegation.overview(db)]

    assert delegation.unmark(db, instrument_id=sol, account_id=hot)
    assert delegation.overview(db) == []
    assert not delegation.unmark(db, instrument_id=sol, account_id=hot)


def test_marking_again_refreshes_the_note(db):
    """The marker describes the present — re-marking is a statement about
    now, not a contradiction, so it refreshes rather than refuses."""
    hot, sol = _account(db), _sol(db)
    assert delegation.mark(db, instrument_id=sol, account_id=hot, note="Everstake")
    assert delegation.mark(db, instrument_id=sol, account_id=hot, note="Chorus One")

    (marker,) = delegation.overview(db)
    assert marker.note == "Chorus One"


def test_marking_an_unknown_pair_is_refused(db):
    hot = _account(db)
    assert not delegation.mark(db, instrument_id=999999, account_id=hot)


# --- No tax meaning ---------------------------------------------------------


def test_a_delegation_does_not_affect_the_holding_period(db):
    """Ownership never changes, so a delegation neither restarts the
    Haltefrist nor extends it to ten years: coins bought, delegated
    mid-hold and sold just past the year stay exempt (§23 Abs. 1 Satz 1
    Nr. 2 EStG) — and the marker creates no §22 income of its own."""
    hot, sol = _account(db), _sol(db)
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    _keep(db, sol, hot)
    bought = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=BOUGHT,
        note=None,
        legs=[
            Leg(account_id=hot, instrument_id=sol, role="in", quantity=Decimal("10")),
            Leg(account_id=hot, instrument_id=eur, role="out", quantity=Decimal("1000")),
        ],
    )
    assert isinstance(bought, int)
    assert delegation.mark(db, instrument_id=sol, account_id=hot, note="Everstake")
    sold = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        note=None,
        legs=[
            Leg(account_id=hot, instrument_id=sol, role="out", quantity=Decimal("10")),
            Leg(account_id=hot, instrument_id=eur, role="in", quantity=Decimal("1500")),
        ],
    )
    assert isinstance(sold, int)

    disposals = section23.year_report(db, FakeReferenceRateSource(), year=2026)
    income = section22.year_report(db, FakeReferenceRateSource(), year=2026)

    (disposal,) = disposals.disposals
    (consumption,) = disposal.consumptions
    assert consumption.acquired_at == BOUGHT
    assert consumption.long_term is True
    assert income.incomes == ()


def test_a_delegation_never_stales_the_lot_materialisation(db):
    """The marker is not an input class of the materialisation (ADR-0014):
    marking and unmarking changes no lot and drifts nothing."""
    hot, sol = _account(db), _sol(db)
    _keep(db, sol, hot)
    lots.fresh_lots(db)
    assert lots.drift(db) == []

    assert delegation.mark(db, instrument_id=sol, account_id=hot)
    assert lots.drift(db) == []
    assert delegation.unmark(db, instrument_id=sol, account_id=hot)
    assert lots.drift(db) == []


# --- Never a transaction ----------------------------------------------------


def test_the_ledger_has_no_delegation_transaction_type():
    """A delegation is location, not a transaction: the vocabulary has no
    type for it, so neither the Admin nor an import can record one — and
    treating it as a transfer to nowhere would consume the lot and destroy
    the holding period on coins that never left the Admin's control."""
    for word in ("delegate", "delegation", "undelegate", "stake", "unstake"):
        assert word not in TRANSACTION_TYPES
        assert word not in TAX_CONSEQUENCES


def test_the_import_warning_names_the_event_and_asks_the_admin(db):
    """Delegation events found during import are surfaced as warnings, never
    imported as transactions — whether coins moved between the Admin's own
    Accounts is the Admin's statement to make, as a self-transfer."""
    warning = delegation.import_warning(event="delegate", symbol="SOL", account_name="Hot wallet")

    assert "delegate" in warning
    assert "SOL" in warning
    assert "Hot wallet" in warning
    assert "did not import" in warning
    assert "self-transfer" in warning
