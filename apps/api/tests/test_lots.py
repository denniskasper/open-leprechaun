"""Tax Lots as a fingerprinted materialisation (ADR-0014): the ledger is the
only source of truth, lots are derived in full from the beginning of time and
stored only so holdings and reports need not replay the ledger, and each
materialisation stamps a per-class fingerprint of its inputs so a stale lot
table is detectable rather than quietly wrong.

The seams are the schema over real Postgres and the lot engine's public
functions — `fresh_lots` (the one read, which never serves a drifted table),
`rebuild` and `drift`.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import fingerprints, instruments, platforms, stances, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import lots

NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


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


def _buy(db, account, instrument, eur, *, quantity="1", cost="100", occurred_at=NOON):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account,
                instrument_id=instrument,
                role="in",
                quantity=Decimal(quantity),
            ),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal(cost)),
        ],
    )
    assert isinstance(created, int)
    return created


# --- What mints a lot -------------------------------------------------------


def test_a_kept_purchase_mints_a_lot_at_its_eur_cost(db):
    """A trade's in-leg mints a lot whose basis is what left plus the fee
    charged against the acquisition — a documented purchase, `cost`."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.5")),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("10000")),
            Leg(
                account_id=account,
                instrument_id=eur,
                role="fee",
                quantity=Decimal("25"),
                charged_against=0,
            ),
        ],
    )

    (lot,) = lots.fresh_lots(db)

    assert lot.account_id == account
    assert lot.instrument_id == btc
    assert lot.acquired_at == NOON
    assert lot.quantity == Decimal("0.5")
    assert lot.basis_eur == Decimal("10025")
    assert lot.basis_source == "cost"


def test_an_inflow_of_an_unacknowledged_instrument_mints_no_lot(db):
    """Deny by default (ADR-0012): the failure mode is an item waiting in the
    inbox, never a holding silently valued at zero — even for a purchase."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _buy(db, account, btc, eur)

    assert lots.fresh_lots(db) == []


def test_an_ignored_or_dangerous_inflow_never_enters_the_cost_basis(db):
    """The position stays visible in the ledger, but no lot carries it."""
    account, eur = _account(db), _eur(db)
    ignored = _btc(db)
    condemned = instruments.create_crypto_token(
        db,
        symbol="FREE",
        name="Free Claim",
        chain="solana",
        contract_address="c1aimfreerewardsexamp1eon1ynotrea1m1nt111111",
    )
    _buy(db, account, ignored, eur)
    _buy(db, account, condemned, eur)
    assert stances.classify(db, ignored, stance="ignored", account_id=account) == []
    assert stances.classify(db, condemned, stance="dangerous") == []

    assert lots.fresh_lots(db) == []


def test_a_transfer_in_mints_no_lot_even_when_kept(db):
    """An unclassified inflow is never assumed to be a purchase: matching
    (16), an Opening Balance (15) or a Stance decision (14) settles it."""
    account, btc = _account(db), _btc(db)
    _keep(db, btc, account)
    transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1"))],
    )

    assert lots.fresh_lots(db) == []


def test_the_numeraire_mints_no_lot(db):
    """EUR is what every basis is expressed in, so it has none of its own —
    even under an explicit kept stance."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, eur, account)
    transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("9000")),
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("0.5")),
        ],
    )

    assert lots.fresh_lots(db) == []


def test_an_opening_balance_mints_a_lot_at_its_declared_estimate(db):
    """The basis is the Admin's declaration, never something observed — the
    lot marked `estimate` so every disposal consuming it can be flagged."""
    account, btc = _account(db), _btc(db)
    _keep(db, btc, account)
    transactions.create_transaction(
        db,
        type="opening_balance",
        occurred_at=NOON,
        note=None,
        reconstructed="basis",
        estimated_basis_eur=Decimal("1234.56"),
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("2"))],
    )

    (lot,) = lots.fresh_lots(db)

    assert lot.quantity == Decimal("2")
    assert lot.basis_eur == Decimal("1234.56")
    assert lot.basis_source == "estimate"
    assert lot.acquired_at == NOON


def test_a_kept_windfall_is_acquired_without_consideration(db):
    """No income and no Anschaffung (BMF 10.05.2022): the lot exists at zero
    basis, marked, so the holding stays visible while ticket 21 keeps its
    disposal out of §23."""
    account, btc = _account(db), _btc(db)
    transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("3"))],
    )
    settled = stances.classify(
        db, btc, stance="kept", account_id=account, settle_inflows_as="windfall"
    )
    assert settled != []

    (lot,) = lots.fresh_lots(db)

    assert lot.basis_eur == Decimal("0")
    assert lot.basis_source == "without_consideration"


def test_income_awaits_its_market_value(db):
    """A staking reward mints at market value on receipt — a price the ledger
    cannot state until tickets 17/18, so the basis is honestly absent rather
    than guessed."""
    account, btc = _account(db), _btc(db)
    _keep(db, btc, account)
    transactions.create_transaction(
        db,
        type="staking_reward",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.01"))],
    )

    (lot,) = lots.fresh_lots(db)

    assert lot.basis_eur is None
    assert lot.basis_source == "market_value"


def test_a_crypto_crypto_trade_awaits_valuation(db):
    """The cost of what left is not yet statable in EUR, so the basis waits —
    None, never a guess of zero."""
    account, btc = _account(db), _btc(db)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ethereum", chain="ethereum")
    _keep(db, btc, account)
    transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.5")),
            Leg(account_id=account, instrument_id=eth, role="out", quantity=Decimal("10")),
        ],
    )

    (lot,) = lots.fresh_lots(db)

    assert lot.basis_eur is None
    assert lot.basis_source == "cost"


def test_one_consideration_across_two_positions_awaits_valuation(db):
    """Splitting what left across several acquisitions needs their relative
    market values, so both lots wait rather than guess a split."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ethereum", chain="ethereum")
    _keep(db, btc, account)
    _keep(db, eth, account)
    transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.5")),
            Leg(account_id=account, instrument_id=eth, role="in", quantity=Decimal("5")),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("20000")),
        ],
    )

    minted = lots.fresh_lots(db)

    assert len(minted) == 2
    assert all(lot.basis_eur is None and lot.basis_source == "cost" for lot in minted)


def test_a_fee_charged_against_the_disposal_does_not_enter_the_basis(db):
    """A fee's treatment follows the leg it was charged against (ADR-0011):
    charged against what left, it is a cost of that disposal, not of this
    acquisition."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.5")),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("10000")),
            Leg(
                account_id=account,
                instrument_id=eur,
                role="fee",
                quantity=Decimal("25"),
                charged_against=1,
            ),
        ],
    )

    (lot,) = lots.fresh_lots(db)

    assert lot.basis_eur == Decimal("10000")


# --- The materialisation and its fingerprint --------------------------------


def test_rebuilding_is_idempotent(db):
    """Two runs over unchanged inputs produce identical lots — identity
    included, because a lot is keyed by the in-leg that minted it."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur)
    _buy(db, account, btc, eur, quantity="2", cost="250", occurred_at=LATER)

    lots.rebuild(db)
    first = lots.fresh_lots(db)
    lots.rebuild(db)
    second = lots.fresh_lots(db)

    assert first == second
    assert len(first) == 2


def test_a_materialisation_records_a_fingerprint_per_input_class(db):
    """Counts and digests per input class (ADR-0014) — including the classes
    whose tickets have not landed yet, declared so their arrival alone marks
    the lots stale."""
    lots.rebuild(db)

    with db.connect() as connection:
        recorded = {
            row.input_class: row
            for row in connection.execute(
                text(
                    "SELECT input_class, row_count, digest FROM input_fingerprint"
                    " WHERE subject = 'tax_lots'"
                )
            )
        }

    assert set(recorded) == {
        "transactions",
        "transaction_legs",
        "instruments",
        "stances",
        "statutory_configuration",
        "tax_election",
        "rates",
        "corporate_actions",
    }
    # The statute rides in with its migration (ticket 09), so a fresh
    # database already has statutory inputs; the unbuilt classes digest empty.
    assert recorded["statutory_configuration"].row_count > 0
    assert recorded["rates"].row_count == 0
    assert recorded["transactions"].row_count == 0


def test_a_never_materialised_table_is_drift_in_every_class(db):
    drifted = lots.drift(db)

    assert {d.input_class for d in drifted} == set(fingerprints.INPUT_CLASSES)
    assert all(d.stored_count is None for d in drifted)


def test_an_edited_ledger_is_detected_and_identified_as_such(db):
    """A revision after a rebuild leaves a fingerprint that no longer
    matches; the drift names the input class that moved."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    transaction_id = _buy(db, account, btc, eur, quantity="1", cost="100")
    lots.rebuild(db)
    assert lots.drift(db) == []

    refused = transactions.replace_transaction(
        db,
        transaction_id,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("150")),
        ],
    )
    assert refused is None

    drifted = lots.drift(db)
    assert "transaction_legs" in {d.input_class for d in drifted}

    lots.rebuild(db)
    assert lots.drift(db) == []


def test_a_note_edit_churns_no_materialisation(db):
    """The fingerprint covers what the derivation reads; prose for the Admin
    is not an input, so it forces no rebuild."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    transaction_id = _buy(db, account, btc, eur)
    lots.rebuild(db)

    with db.begin() as connection:
        connection.execute(
            text("UPDATE transaction SET note = 'weekly savings plan' WHERE id = :id"),
            {"id": transaction_id},
        )

    assert lots.drift(db) == []


def test_a_stance_decision_reaches_the_next_read_by_itself(db):
    """Keeping an Instrument drifts the stances class, and the very next
    read rebuilds — the lot appears without anyone asking for a rebuild."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _buy(db, account, btc, eur)
    assert lots.fresh_lots(db) == []

    _keep(db, btc, account)

    assert "stances" in {d.input_class for d in lots.drift(db)}
    (lot,) = lots.fresh_lots(db)
    assert lot.instrument_id == btc


def test_a_corrected_statutory_value_marks_the_lots_stale(db):
    """ADR-0014's headline consequence: correcting a rate changes every
    figure resting on it while no transaction has moved — and the fingerprint
    must see it."""
    lots.rebuild(db)
    assert lots.drift(db) == []

    with db.begin() as connection:
        connection.execute(
            text(
                "UPDATE statutory_value SET value = value + 1"
                " WHERE year = 2026 AND key = 'private_sale_exemption_limit'"
            )
        )
    try:
        drifted = {d.input_class for d in lots.drift(db)}
    finally:
        with db.begin() as connection:
            connection.execute(
                text(
                    "UPDATE statutory_value SET value = value - 1"
                    " WHERE year = 2026 AND key = 'private_sale_exemption_limit'"
                )
            )

    assert drifted == {"statutory_configuration"}


def test_deleting_a_transaction_never_blocks_on_its_lot(db):
    """The cache follows the ledger, not the other way round: the lot goes by
    cascade, and the drifted fingerprint marks the table for rebuild."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    transaction_id = _buy(db, account, btc, eur)
    lots.rebuild(db)

    assert transactions.delete_transaction(db, transaction_id)

    with db.connect() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM tax_lot")).scalar_one()
    assert remaining == 0
    assert lots.drift(db) != []
    assert lots.fresh_lots(db) == []


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_refuses_a_lot_outside_the_basis_vocabulary(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur)
    lots.rebuild(db)

    for defect in (
        "basis_source = 'guesswork'",
        "basis_eur = -1",
        "quantity = 0",
        "basis_source = 'without_consideration'",  # basis stays 100, not 0
        "basis_source = 'without_consideration', basis_eur = NULL",  # NULL is not zero
        "basis_source = 'estimate', basis_eur = NULL",
    ):
        with pytest.raises(IntegrityError), db.begin() as connection:
            connection.execute(text(f"UPDATE tax_lot SET {defect}"))
