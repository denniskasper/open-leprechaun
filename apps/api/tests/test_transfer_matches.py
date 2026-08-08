"""Self-transfer matching (ticket 16): moving assets between the Admin's own
Accounts stops looking like a sale and a fresh purchase. The app proposes
candidate pairs by Instrument, quantity within a fee tolerance and time
window; the Admin confirms or rejects each one — nothing links itself — and
an unmatched transfer stays visible as unmatched.

The seams are the schema over real Postgres, the pure candidate rule, the
matching overview, and the HTTP endpoints. What a confirmed link does to the
lot table is tests/test_lots.py's business.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments, platforms, stances, transactions
from open_leprechaun.repositories import transfer_matches as repository
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import transfer_matches as service

NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
SOON = NOON + timedelta(minutes=20)


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _cold_account(db):
    return _account(db, platform_name="BitBox02", kind="cold_storage", name="Savings")


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _btc(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _transfer_out(db, account, instrument, *, quantity="1", occurred_at=NOON):
    created = transactions.create_transaction(
        db,
        type="transfer_out",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account, instrument_id=instrument, role="out", quantity=Decimal(quantity)
            )
        ],
    )
    assert isinstance(created, int)
    return _leg_of(db, created)


def _transfer_in(db, account, instrument, *, quantity="1", occurred_at=SOON):
    created = transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity))
        ],
    )
    assert isinstance(created, int)
    return _leg_of(db, created)


def _leg_of(db, transaction_id):
    with db.connect() as connection:
        return connection.execute(
            text("SELECT id FROM transaction_leg WHERE transaction_id = :id"),
            {"id": transaction_id},
        ).scalar_one()


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_refuses_a_verdict_outside_the_vocabulary(db):
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transfer_match (out_leg_id, in_leg_id, verdict)"
                " VALUES (:out, :in, 'maybe')"
            ),
            {"out": out_leg, "in": in_leg},
        )


def test_each_pair_holds_exactly_one_decision(db):
    """Confirm and reject cannot contradict each other over the same pair."""
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="rejected"), int
    )

    refused = repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed")

    assert refused is repository.Refusal.already_decided


def test_a_leg_belongs_to_at_most_one_confirmed_match(db):
    """A parcel cannot leave for two destinations, nor arrive twice — but any
    number of rejections may accumulate against the same leg."""
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    first_in = _transfer_in(db, cold, btc)
    second_in = _transfer_in(db, cold, btc, occurred_at=SOON + timedelta(minutes=5))
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=first_in, verdict="confirmed"), int
    )

    refused = repository.decide(db, out_leg_id=out_leg, in_leg_id=second_in, verdict="confirmed")

    assert refused is repository.Refusal.already_matched
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=second_in, verdict="rejected"), int
    )


def test_decisions_follow_their_legs_by_cascade(db):
    """Revising or deleting a Transaction swaps its legs away, and the
    decision honestly returns the transfer to unmatched rather than pointing
    at quantities the Admin never confirmed."""
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed"), int
    )

    with db.connect() as connection:
        transaction_id = connection.execute(
            text("SELECT transaction_id FROM transaction_leg WHERE id = :id"), {"id": in_leg}
        ).scalar_one()
    assert transactions.delete_transaction(db, transaction_id)

    assert repository.list_decisions(db) == []


# --- The candidate rule -----------------------------------------------------


def _side(instrument_id=1, account_id=1, quantity="1", occurred_at=NOON):
    return service.TransferLeg(
        leg_id=0,
        transaction_id=0,
        occurred_at=occurred_at,
        note=None,
        quantity=Decimal(quantity),
        account_id=account_id,
        account_name="",
        platform_name="",
        instrument_id=instrument_id,
        instrument_symbol="",
        instrument_name="",
    )


def test_a_candidate_is_the_same_instrument_between_two_accounts():
    assert service.is_candidate(_side(account_id=1), _side(account_id=2, occurred_at=SOON))
    assert not service.is_candidate(_side(account_id=1), _side(account_id=1, occurred_at=SOON))
    assert not service.is_candidate(
        _side(instrument_id=1), _side(instrument_id=2, account_id=2, occurred_at=SOON)
    )


def test_the_fee_tolerance_bounds_what_went_missing_en_route():
    """What arrived may fall short of what left by at most the tolerance —
    a network fee — and may never exceed it."""
    outgoing = _side(quantity="1")
    assert service.is_candidate(outgoing, _side(account_id=2, quantity="1", occurred_at=SOON))
    assert service.is_candidate(outgoing, _side(account_id=2, quantity="0.99", occurred_at=SOON))
    assert not service.is_candidate(
        outgoing, _side(account_id=2, quantity="0.989", occurred_at=SOON)
    )
    assert not service.is_candidate(
        outgoing, _side(account_id=2, quantity="1.001", occurred_at=SOON)
    )


def test_the_time_window_is_symmetric():
    """Venue clocks disagree, so a deposit stamped before the withdrawal is
    still proposable — within the window on either side."""
    outgoing = _side()
    inside = NOON + service.TIME_WINDOW
    outside = NOON + service.TIME_WINDOW + timedelta(seconds=1)
    assert service.is_candidate(outgoing, _side(account_id=2, occurred_at=inside))
    earlier = NOON - timedelta(hours=1)
    assert service.is_candidate(outgoing, _side(account_id=2, occurred_at=earlier))
    assert not service.is_candidate(outgoing, _side(account_id=2, occurred_at=outside))


# --- The matching overview --------------------------------------------------


def test_the_overview_proposes_a_candidate_and_stores_nothing(db):
    """Nothing links itself: a proposal is a derived pair, and reading the
    overview writes no row."""
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc, quantity="0.004")
    in_leg = _transfer_in(db, cold, btc, quantity="0.004")

    overview = service.matching_overview(db)

    (candidate,) = overview.candidates
    assert candidate.outgoing.leg_id == out_leg
    assert candidate.incoming.leg_id == in_leg
    assert [leg.leg_id for leg in overview.unmatched_outgoing] == [out_leg]
    assert [leg.leg_id for leg in overview.unmatched_incoming] == [in_leg]
    with db.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM transfer_match")).scalar_one() == 0


def test_a_rejected_pair_is_never_proposed_again(db):
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="rejected"), int
    )

    overview = service.matching_overview(db)

    assert overview.candidates == []
    # The transfers themselves stay visibly unmatched — a rejection settles
    # the pair, not the legs.
    assert [leg.leg_id for leg in overview.unmatched_outgoing] == [out_leg]
    assert [leg.leg_id for leg in overview.unmatched_incoming] == [in_leg]


def test_a_confirmed_leg_leaves_the_unmatched_lists_and_the_proposals(db):
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    other_in = _transfer_in(db, cold, btc, occurred_at=SOON + timedelta(minutes=5))
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed"), int
    )

    overview = service.matching_overview(db)

    assert overview.unmatched_outgoing == []
    assert [leg.leg_id for leg in overview.unmatched_incoming] == [other_in]
    assert overview.candidates == []
    (decision,) = overview.decisions
    assert decision.verdict == "confirmed"
    assert decision.outgoing.leg_id == out_leg
    assert decision.incoming.leg_id == in_leg


def test_the_numeraire_never_awaits_a_match(db):
    """Moving EUR is not a disposal (ADR-0011), so its transfers are neither
    unmatched nor proposable."""
    account, cold, eur = _account(db), _cold_account(db), _eur(db)
    _transfer_out(db, account, eur, quantity="500")
    _transfer_in(db, cold, eur, quantity="500")

    overview = service.matching_overview(db)

    assert overview.unmatched_outgoing == []
    assert overview.unmatched_incoming == []
    assert overview.candidates == []


# --- The inbox stands aside -------------------------------------------------


def test_a_matched_transfer_in_is_not_settled_by_a_keep(db):
    """Keeping an Instrument settles its pending unclassified inflows as an
    airdrop or a windfall (ticket 14) — but a confirmed self-transfer is
    already classified: it is the Admin's own parcel arriving, and a keep
    must not retype it."""
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed"), int
    )

    settled = stances.classify(
        db, btc, stance="kept", account_id=cold, settle_inflows_as="windfall"
    )

    assert settled == []
    with db.connect() as connection:
        remaining = connection.execute(
            text("SELECT type FROM transaction WHERE occurred_at = :at"), {"at": SOON}
        ).scalar_one()
    assert remaining == "transfer_in"


def test_a_matched_arrival_no_longer_waits_in_the_inbox(db):
    """The confirmation is the classification: once the pair's only inflow is
    a confirmed self-transfer, nothing waits on a stance decision."""
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    assert len(stances.list_inbox(db)) == 1

    assert isinstance(
        repository.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed"), int
    )

    assert stances.list_inbox(db) == []


# --- The HTTP seam ----------------------------------------------------------


def test_the_api_walks_a_proposal_to_a_confirmed_link(client, db):
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc, quantity="0.004")
    in_leg = _transfer_in(db, cold, btc, quantity="0.004")

    proposed = client.get("/api/transfer-matches").json()
    (candidate,) = proposed["candidates"]
    assert candidate["outgoing"]["leg_id"] == out_leg
    assert candidate["incoming"]["leg_id"] == in_leg
    assert candidate["outgoing"]["quantity"] == "0.004"

    confirmed = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "confirmed"},
    )
    assert confirmed.status_code == 201

    linked = client.get("/api/transfer-matches").json()
    assert linked["candidates"] == []
    assert linked["unmatched_outgoing"] == []
    assert linked["unmatched_incoming"] == []
    (decision,) = linked["decisions"]
    assert decision["verdict"] == "confirmed"
    assert decision["id"] == confirmed.json()["id"]


def test_the_api_undoes_a_decision(client, db):
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    decided = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "rejected"},
    ).json()

    assert client.delete(f"/api/transfer-matches/{decided['id']}").status_code == 204

    overview = client.get("/api/transfer-matches").json()
    assert len(overview["candidates"]) == 1
    assert client.delete(f"/api/transfer-matches/{decided['id']}").status_code == 404


def test_the_api_refuses_what_cannot_be_a_self_transfer(client, db):
    """Wrong shapes are refused with a sentence naming the defect — but the
    tolerance and window are proposal heuristics, not confirmation rules, so
    an out-of-window pair the Admin knows better about goes through."""
    account, cold, eur, btc = _account(db), _cold_account(db), _eur(db), _btc(db)
    sol = instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")
    trade = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("100")),
        ],
    )
    trade_in_leg = next(
        leg["id"]
        for transaction in client.get("/api/transactions").json()
        if transaction["id"] == trade
        for leg in transaction["legs"]
        if leg["role"] == "in"
    )

    out_leg = _transfer_out(db, account, btc, quantity="1")
    for in_leg, defect in (
        (trade_in_leg, "The incoming side of a match is the in-leg of a transfer in."),
        (
            _transfer_in(db, cold, sol),
            "A self-transfer moves one Instrument — these legs carry two.",
        ),
        (
            _transfer_in(db, account, btc, occurred_at=SOON + timedelta(minutes=1)),
            "A self-transfer moves between two Accounts — these legs share one.",
        ),
        (
            _transfer_in(db, cold, btc, quantity="2", occurred_at=SOON + timedelta(minutes=2)),
            "More arrived than left — that cannot be one self-transfer.",
        ),
    ):
        response = client.post(
            "/api/transfer-matches",
            json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "confirmed"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == defect

    late = _transfer_in(db, cold, btc, occurred_at=NOON + timedelta(days=30))
    accepted = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": late, "verdict": "confirmed"},
    )
    assert accepted.status_code == 201


def test_the_api_refuses_a_numeraire_match(client, db):
    account, cold, eur = _account(db), _cold_account(db), _eur(db)
    out_leg = _transfer_out(db, account, eur, quantity="500")
    in_leg = _transfer_in(db, cold, eur, quantity="500")

    response = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "confirmed"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The numéraire moves freely — its transfer needs no match."


def test_the_api_answers_conflict_over_an_already_linked_leg(client, db):
    account, cold, btc = _account(db), _cold_account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)
    in_leg = _transfer_in(db, cold, btc)
    second_in = _transfer_in(db, cold, btc, occurred_at=SOON + timedelta(minutes=5))
    assert (
        client.post(
            "/api/transfer-matches",
            json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "confirmed"},
        ).status_code
        == 201
    )

    conflicted = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": second_in, "verdict": "confirmed"},
    )
    repeated = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "rejected"},
    )

    assert conflicted.status_code == 409
    assert repeated.status_code == 409


def test_the_api_answers_not_found_over_a_missing_leg(client, db):
    account, btc = _account(db), _btc(db)
    out_leg = _transfer_out(db, account, btc)

    response = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": 999999, "verdict": "confirmed"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "No such leg."
