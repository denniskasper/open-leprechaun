"""Stance and the unacknowledged inbox (ADR-0012): anything arriving that the
Admin has never classified waits in an inbox instead of entering the cost
basis, and classifying it is a deliberate act with three outcomes — kept,
ignored, dangerous.

The seams are the schema over real Postgres, the repository, the service that
answers the questions later tickets must ask it (does this inflow mint a lot,
may this Instrument acquire a price source), and the HTTP endpoints.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments, platforms, stances, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.seed import seed
from open_leprechaun.services import stances as stance_service
from open_leprechaun.services.instruments import overview as instrument_overview

NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    if platform_id is None:
        platform_id = next(
            row.id for row in platforms.list_platforms(db) if row.name == platform_name
        )
    created = platforms.create_account(db, platform_id, name=name)
    if created is platforms.Refusal.name_taken:
        return next(row.id for row in platforms.list_accounts(db) if row.name == name)
    return created


def _spam_token(db, symbol="USDC", name="USDC Rewards Claim"):
    return instruments.create_crypto_token(
        db,
        symbol=symbol,
        name=name,
        chain="solana",
        contract_address="c1aimusdcrewardsexamp1eon1ynotrea1m1nt111111",
    )


def _btc(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _inflow(db, account, instrument, *, type="transfer_in", occurred_at=NOON, quantity="1999.75"):
    return transactions.create_transaction(
        db,
        type=type,
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity))
        ],
    )


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_ties_the_scope_to_the_stance(db):
    """Dangerous is global exactly; kept and ignored sit on an Account — a row
    whose scope disagrees with its stance is refused by the schema."""
    account, token = _account(db), _spam_token(db)
    for stance, account_id in (("kept", None), ("ignored", None), ("dangerous", account)):
        with pytest.raises(IntegrityError), db.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO instrument_stance (instrument_id, account_id, stance)"
                    " VALUES (:instrument, :account, :stance)"
                ),
                {"instrument": token, "account": account_id, "stance": stance},
            )


def test_the_schema_refuses_a_stance_outside_the_vocabulary(db):
    token = _spam_token(db)
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument_stance (instrument_id, stance)"
                " VALUES (:instrument, 'suspicious')"
            ),
            {"instrument": token},
        )


def test_each_scope_holds_exactly_one_decision(db):
    """One global row per Instrument, one row per Instrument and Account —
    a second decision replaces the first, it never sits beside it."""
    account, token = _account(db), _spam_token(db)
    assert stances.classify(db, token, stance="dangerous") == []
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("INSERT INTO instrument_stance (instrument_id, stance) VALUES (:t, 'dangerous')"),
            {"t": token},
        )
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument_stance (instrument_id, account_id, stance)"
                " VALUES (:t, :a, 'kept')"
            ),
            {"t": token, "a": account},
        )
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument_stance (instrument_id, account_id, stance)"
                " VALUES (:t, :a, 'ignored')"
            ),
            {"t": token, "a": account},
        )


# --- Classifying is a deliberate act ----------------------------------------


def test_a_new_instrument_is_unacknowledged_by_default(db):
    """No row is the default: unacknowledged means only that nobody has
    looked yet."""
    account, token = _account(db), _spam_token(db)

    assert stance_service.stance_of(db, token, account) == "unacknowledged"


def test_classifying_reclassifies_cleanly_between_kept_and_ignored(db):
    account, token = _account(db), _spam_token(db)

    stances.classify(db, token, stance="ignored", account_id=account)
    assert stance_service.stance_of(db, token, account) == "ignored"

    stances.classify(db, token, stance="kept", account_id=account)
    assert stance_service.stance_of(db, token, account) == "kept"


def test_dangerous_applies_to_the_instrument_globally(db):
    """A kept holding at one Account does not soften a dangerous verdict —
    a token whose approval drains a wallet is dangerous everywhere."""
    kraken, phantom = _account(db), _account(db, "Phantom", "software_wallet", "Hot wallet")
    token = _spam_token(db)
    stances.classify(db, token, stance="kept", account_id=kraken)

    stances.classify(db, token, stance="dangerous")

    assert stance_service.stance_of(db, token, kraken) == "dangerous"
    assert stance_service.stance_of(db, token, phantom) == "dangerous"


def test_kept_and_ignored_apply_per_account(db):
    """A genuine holding bought at one venue coexists with dust of the same
    Instrument sprayed at another."""
    kraken, phantom = _account(db), _account(db, "Phantom", "software_wallet", "Hot wallet")
    token = _spam_token(db)

    stances.classify(db, token, stance="kept", account_id=kraken)
    stances.classify(db, token, stance="ignored", account_id=phantom)

    assert stance_service.stance_of(db, token, kraken) == "kept"
    assert stance_service.stance_of(db, token, phantom) == "ignored"


def test_clearing_a_stance_returns_the_pair_to_unacknowledged(db):
    account, token = _account(db), _spam_token(db)
    stances.classify(db, token, stance="ignored", account_id=account)
    stances.classify(db, token, stance="dangerous")

    assert stances.clear(db, token) is True
    assert stances.clear(db, token) is False
    assert stance_service.stance_of(db, token, account) == "ignored"
    assert stances.clear(db, token, account_id=account) is True
    assert stance_service.stance_of(db, token, account) == "unacknowledged"


def test_a_per_account_decision_under_a_dangerous_verdict_is_refused(db, client):
    """The global verdict outranks a per-Account decision, so keeping under it
    would settle inflows a dangerous stance forbids — the verdict goes first."""
    account, token = _account(db), _spam_token(db)
    _inflow(db, account, token)
    stances.classify(db, token, stance="dangerous")

    refused = stances.classify(
        db, token, stance="kept", account_id=account, settle_inflows_as="windfall"
    )

    assert refused is stances.Refusal.marked_dangerous
    assert {t.type for t in transactions.list_transactions(db)} == {"transfer_in"}
    over_http = client.put(
        f"/api/instruments/{token}/stance", json={"stance": "kept", "account_id": account}
    )
    assert over_http.status_code == 409
    assert "dangerous" in over_http.json()["detail"]


def test_classifying_over_a_missing_foundation_says_which(db):
    account, token = _account(db), _spam_token(db)

    assert (
        stances.classify(db, 12345, stance="kept", account_id=account)
        is stances.Refusal.no_such_instrument
    )
    assert (
        stances.classify(db, token, stance="kept", account_id=12345)
        is stances.Refusal.no_such_account
    )


# --- An unacknowledged inflow is recorded but mints no lot ------------------


def test_an_inflow_of_an_unacknowledged_instrument_is_recorded(db):
    """The transaction is always recorded whatever the stance, so the ledger
    still reconciles against the wallet; only lot creation is withheld."""
    account, token = _account(db), _spam_token(db)

    transaction_id = _inflow(db, account, token)

    assert isinstance(transaction_id, int)
    (recorded,) = transactions.list_transactions(db)
    assert recorded.id == transaction_id


def test_only_a_kept_inflow_mints_a_lot():
    """The rule ticket 19's lot engine reads: unacknowledged is deny by
    default — the failure mode is an item awaiting a decision, not a holding
    silently valued at zero — and ignored or dangerous never enter the cost
    basis either."""
    assert stance_service.inflow_mints_lot("kept") is True
    for stance in ("unacknowledged", "ignored", "dangerous"):
        assert stance_service.inflow_mints_lot(stance) is False


# --- The inbox ---------------------------------------------------------------


def test_the_inbox_lists_what_arrived_unclassified_and_where(db):
    account, token = _account(db), _spam_token(db)
    _inflow(db, account, token)
    _inflow(db, account, token, occurred_at=LATER, quantity="0.25")

    (item,) = stance_service.inbox(db)

    assert item.instrument_id == token
    assert item.symbol == "USDC"
    assert item.account_id == account
    assert item.platform_name == "Kraken"
    assert item.account_name == "Main"
    assert item.unclassified_inflow_count == 2
    assert item.unclassified_quantity == Decimal("2000.00")
    assert item.last_inflow_at == LATER


def test_the_same_instrument_waits_once_per_account(db):
    kraken, phantom = _account(db), _account(db, "Phantom", "software_wallet", "Hot wallet")
    token = _spam_token(db)
    _inflow(db, kraken, token)
    _inflow(db, phantom, token, occurred_at=LATER)

    items = stance_service.inbox(db)

    assert {(item.instrument_id, item.account_id) for item in items} == {
        (token, kraken),
        (token, phantom),
    }


def test_a_classified_pair_leaves_the_inbox_and_a_dangerous_instrument_leaves_everywhere(db):
    kraken, phantom = _account(db), _account(db, "Phantom", "software_wallet", "Hot wallet")
    token = _spam_token(db)
    _inflow(db, kraken, token)
    _inflow(db, phantom, token, occurred_at=LATER)

    stances.classify(db, token, stance="ignored", account_id=kraken)
    assert {(i.instrument_id, i.account_id) for i in stance_service.inbox(db)} == {(token, phantom)}

    stances.classify(db, token, stance="dangerous")
    assert stance_service.inbox(db) == []


def test_a_hand_recorded_purchase_still_awaits_a_stance_but_asks_no_question(db):
    """A trade's in-leg puts the pair in the inbox — classification is its own
    deliberate act — yet it is no unsolicited inflow, so there is nothing for
    the counter-performance question to settle."""
    account, eur, token = (
        _account(db),
        instruments.create_cash(db, symbol="EUR", name="Euro"),
        _spam_token(db),
    )
    transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("10")),
            Leg(account_id=account, instrument_id=token, role="in", quantity=Decimal("100")),
        ],
    )

    (item,) = [i for i in stance_service.inbox(db) if i.instrument_id == token]

    assert item.unclassified_inflow_count == 0
    assert item.unclassified_quantity == Decimal("0")


def test_the_numeraire_needs_no_stance(db):
    """EUR's movement is not a disposal and it enters no cost basis, so its
    arrival never waits on a classification."""
    account = _account(db, "Sparkasse", "bank", "Giro")
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    instruments.designate_numeraire(db, eur)
    _inflow(db, account, eur, type="interest")

    assert stance_service.inbox(db) == []


# --- Acknowledging asks the counter-performance question --------------------


def test_the_answer_decides_what_the_unsolicited_inflow_settles_as():
    """Received for a counter-performance it is an airdrop — §22 income at
    market value on receipt. Received for nothing it is a windfall."""
    assert stance_service.settled_inflow_type(received_for_counter_performance=True) == "airdrop"
    assert stance_service.settled_inflow_type(received_for_counter_performance=False) == "windfall"


def test_keeping_settles_pending_unclassified_inflows(db):
    account, token = _account(db), _spam_token(db)
    first = _inflow(db, account, token)
    second = _inflow(db, account, token, occurred_at=LATER)

    settled = stances.classify(
        db, token, stance="kept", account_id=account, settle_inflows_as="windfall"
    )

    assert sorted(settled) == sorted([first, second])
    assert {t.type for t in transactions.list_transactions(db)} == {"windfall"}


def test_keeping_settles_only_this_account_and_only_unclassified_inflows(db):
    kraken, phantom = _account(db), _account(db, "Phantom", "software_wallet", "Hot wallet")
    token = _spam_token(db)
    here = _inflow(db, kraken, token)
    elsewhere = _inflow(db, phantom, token, occurred_at=LATER)
    reward = _inflow(db, kraken, token, type="staking_reward", occurred_at=LATER)

    settled = stances.classify(
        db, token, stance="kept", account_id=kraken, settle_inflows_as="airdrop"
    )

    assert settled == [here]
    by_id = {t.id: t.type for t in transactions.list_transactions(db)}
    assert by_id[elsewhere] == "transfer_in"
    assert by_id[reward] == "staking_reward"


# --- Ignored and dangerous can never acquire a price source -----------------


def test_an_ignored_or_dangerous_instrument_may_not_acquire_a_price_source(db):
    account, token = _account(db), _spam_token(db)

    assert stance_service.may_acquire_price_source(db, token) is True

    stances.classify(db, token, stance="ignored", account_id=account)
    assert stance_service.may_acquire_price_source(db, token) is False

    stances.classify(db, token, stance="dangerous")
    assert stance_service.may_acquire_price_source(db, token) is False


def test_a_holding_kept_anywhere_keeps_the_instrument_priceable(db):
    """Dust ignored at one venue must not unprice the genuine holding kept at
    another — only an Instrument that is ignored wherever it appears, or
    dangerous, is barred."""
    kraken, phantom = _account(db), _account(db, "Phantom", "software_wallet", "Hot wallet")
    token = _spam_token(db)
    stances.classify(db, token, stance="ignored", account_id=phantom)
    stances.classify(db, token, stance="kept", account_id=kraken)

    assert stance_service.may_acquire_price_source(db, token) is True

    stances.classify(db, token, stance="dangerous")
    assert stance_service.may_acquire_price_source(db, token) is False


# --- The HTTP seam ----------------------------------------------------------


def test_the_api_lists_the_inbox(client, db):
    account, token = _account(db), _spam_token(db)
    _inflow(db, account, token)

    (item,) = client.get("/api/inbox").json()

    assert item["instrument_id"] == token
    assert item["symbol"] == "USDC"
    assert item["name"] == "USDC Rewards Claim"
    assert item["account_id"] == account
    assert item["platform_name"] == "Kraken"
    assert item["account_name"] == "Main"
    assert item["unclassified_inflow_count"] == 1
    assert item["unclassified_quantity"] == "1999.75"
    assert item["last_inflow_at"] == "2026-03-14T12:00:00Z"


def test_the_api_keeps_an_instrument_defaulting_the_question_to_no(client, db):
    """Acknowledging asks whether the inflow was received for a
    counter-performance; unanswered, the answer is no and the inflow settles
    as a windfall."""
    account, token = _account(db), _spam_token(db)
    inflow = _inflow(db, account, token)

    response = client.put(
        f"/api/instruments/{token}/stance", json={"stance": "kept", "account_id": account}
    )

    assert response.status_code == 200
    assert response.json() == {"settled_transaction_ids": [inflow]}
    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "windfall"
    assert client.get("/api/inbox").json() == []


def test_the_api_settles_an_inflow_received_for_a_counter_performance_as_an_airdrop(client, db):
    account, token = _account(db), _spam_token(db)
    _inflow(db, account, token)

    response = client.put(
        f"/api/instruments/{token}/stance",
        json={"stance": "kept", "account_id": account, "received_for_counter_performance": True},
    )

    assert response.status_code == 200
    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "airdrop"


def test_the_api_marks_dangerous_globally_and_ignores_per_account(client, db):
    account, token = _account(db), _spam_token(db)
    _inflow(db, account, token)

    ignored = client.put(
        f"/api/instruments/{token}/stance", json={"stance": "ignored", "account_id": account}
    )
    assert ignored.status_code == 200
    assert ignored.json() == {"settled_transaction_ids": []}

    dangerous = client.put(f"/api/instruments/{token}/stance", json={"stance": "dangerous"})
    assert dangerous.status_code == 200

    # Ignoring or condemning settles nothing — the inflows stay as recorded.
    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "transfer_in"


def test_the_api_refuses_a_stance_whose_scope_is_wrong(client, db):
    account, token = _account(db), _spam_token(db)

    unscoped = client.put(f"/api/instruments/{token}/stance", json={"stance": "kept"})
    scoped = client.put(
        f"/api/instruments/{token}/stance", json={"stance": "dangerous", "account_id": account}
    )
    unasked = client.put(
        f"/api/instruments/{token}/stance",
        json={"stance": "ignored", "account_id": account, "received_for_counter_performance": True},
    )

    assert unscoped.status_code == 422
    assert "Account" in unscoped.json()["detail"]
    assert scoped.status_code == 422
    assert unasked.status_code == 422
    assert "counter-performance" in unasked.json()["detail"]


def test_the_api_answers_not_found_over_a_missing_instrument_or_account(client, db):
    account, token = _account(db), _spam_token(db)

    missing_instrument = client.put(
        "/api/instruments/12345/stance", json={"stance": "kept", "account_id": account}
    )
    missing_account = client.put(
        f"/api/instruments/{token}/stance", json={"stance": "kept", "account_id": 12345}
    )

    assert missing_instrument.status_code == 404
    assert "Instrument" in missing_instrument.json()["detail"]
    assert missing_account.status_code == 404
    assert "Account" in missing_account.json()["detail"]


def test_the_api_returns_a_pair_to_unacknowledged(client, db):
    account, token = _account(db), _spam_token(db)
    _inflow(db, account, token)
    client.put(f"/api/instruments/{token}/stance", json={"stance": "dangerous"})
    assert client.get("/api/inbox").json() == []

    removed = client.delete(f"/api/instruments/{token}/stance")

    assert removed.status_code == 204
    assert len(client.get("/api/inbox").json()) == 1
    assert client.delete(f"/api/instruments/{token}/stance").status_code == 404


def test_an_ignored_or_dangerous_position_stays_visible_with_its_stance_stated(client, db):
    """Never hidden: the holding genuinely exists on-chain, so the Instrument
    keeps appearing in the overview carrying the warning the UI must show."""
    account, token = _account(db), _spam_token(db)
    stances.classify(db, token, stance="ignored", account_id=account)

    (instrument,) = [i for i in instrument_overview(db) if i.id == token]
    assert instrument.dangerous is False
    assert [(s.account_id, s.stance) for s in instrument.stances] == [(account, "ignored")]

    stances.classify(db, token, stance="dangerous")
    (via_api,) = [i for i in client.get("/api/instruments").json() if i["id"] == token]
    assert via_api["dangerous"] is True
    assert via_api["stances"] == [{"account_id": account, "stance": "ignored"}]


# --- The seed ---------------------------------------------------------------


def test_the_seed_leaves_one_arrival_waiting_in_the_inbox(db):
    """The development database demonstrates the whole feature: the genuine
    holdings kept, and one same-ticker spam token waiting on a decision."""
    seed(db)

    (item,) = stance_service.inbox(db)
    assert item.symbol == "USDC"
    assert item.platform_name == "Phantom"
    assert item.unclassified_inflow_count == 1


def test_the_seed_survives_the_inbox_being_worked_through(db):
    """Acknowledging retypes the seeded inflow; a later seed run must respect
    that decision rather than resurrect the unclassified arrival."""
    seed(db)
    (item,) = stance_service.inbox(db)
    stances.classify(
        db,
        item.instrument_id,
        stance="kept",
        account_id=item.account_id,
        settle_inflows_as="windfall",
    )

    seed(db)

    assert stance_service.inbox(db) == []
    with db.connect() as connection:
        windfalls = connection.execute(
            text("SELECT count(*) FROM transaction WHERE type = 'windfall'")
        ).scalar_one()
    assert windfalls == 1
