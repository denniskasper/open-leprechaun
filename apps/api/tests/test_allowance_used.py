"""The allowance used at source (issue 28): for a broker or bank Platform and
a Tax Year, how much of the Sparerpauschbetrag its Freistellungsauftrag used,
exactly as the institution's annual tax certificate states it.

The seams are the HTTP endpoints through the app, and the schema's own
constraints over real Postgres.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import platforms


def _insert(db, platform_id, year, amount):
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO allowance_used (platform_id, year, amount_eur)"
                " VALUES (:platform_id, :year, :amount)"
            ),
            {"platform_id": platform_id, "year": year, "amount": amount},
        )


def test_the_schema_refuses_a_negative_used_amount(db):
    broker = platforms.create_platform(db, name="Scalable", kind="broker")

    with pytest.raises(IntegrityError):
        _insert(db, broker, 2025, "-1")


def test_the_schema_holds_one_used_amount_per_platform_and_year(db):
    broker = platforms.create_platform(db, name="Scalable", kind="broker")
    _insert(db, broker, 2025, "1.00")

    with pytest.raises(IntegrityError):
        _insert(db, broker, 2025, "2.00")


def test_the_schema_keeps_a_platform_holding_a_used_amount(db):
    """The backstop under the removal rule: a past year's tax rests on the
    figure, so the Platform it was entered at cannot be deleted from under it."""
    broker = platforms.create_platform(db, name="Scalable", kind="broker")
    _insert(db, broker, 2025, "1.00")

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(text("DELETE FROM platform WHERE id = :id"), {"id": broker})


def _platform(client, name="Scalable", kind="broker") -> int:
    return client.post("/api/platforms", json={"name": name, "kind": kind}).json()["id"]


def _used(client, platform_id) -> list[dict]:
    (platform,) = [p for p in client.get("/api/platforms").json() if p["id"] == platform_id]
    return platform["allowance_used"]


def test_a_used_amount_is_stored_and_listed_on_its_platform(client, db):
    broker = _platform(client)

    stored = client.put(
        f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "412.37"}
    )

    assert stored.status_code == 204
    assert _used(client, broker) == [{"year": 2025, "amount_eur": "412.37"}]


def test_storing_a_year_that_already_has_a_figure_replaces_it(client, db):
    """Correcting a typo needs no separate delete."""
    broker = _platform(client)
    client.put(f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "412.37"})

    replaced = client.put(
        f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "421.37"}
    )

    assert replaced.status_code == 204
    assert _used(client, broker) == [{"year": 2025, "amount_eur": "421.37"}]


def test_zero_is_a_figure_of_its_own(client, db):
    """An order that used nothing is stated, not left unknown."""
    broker = _platform(client)

    stored = client.put(f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "0"})

    assert stored.status_code == 204
    assert _used(client, broker) == [{"year": 2025, "amount_eur": "0.00"}]


def test_a_cleared_year_is_gone_and_clearing_an_empty_year_is_no_error(client, db):
    broker = _platform(client)
    client.put(f"/api/platforms/{broker}/allowance-used/2024", json={"amount_eur": "100.00"})
    client.put(f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "200.00"})

    assert client.delete(f"/api/platforms/{broker}/allowance-used/2024").status_code == 204
    assert _used(client, broker) == [{"year": 2025, "amount_eur": "200.00"}]
    assert client.delete(f"/api/platforms/{broker}/allowance-used/2024").status_code == 204
    assert client.delete(f"/api/platforms/{broker}/allowance-used/2019").status_code == 204
    assert _used(client, broker) == [{"year": 2025, "amount_eur": "200.00"}]


def test_used_amounts_are_listed_by_year_on_their_own_platform(client, db):
    broker = _platform(client, "Scalable", "broker")
    bank = _platform(client, "Sparkasse", "bank")
    for year, amount in (("2025", "30.00"), ("2023", "10.00"), ("2024", "20.00")):
        client.put(f"/api/platforms/{broker}/allowance-used/{year}", json={"amount_eur": amount})
    client.put(f"/api/platforms/{bank}/allowance-used/2024", json={"amount_eur": "5.50"})

    assert _used(client, broker) == [
        {"year": 2023, "amount_eur": "10.00"},
        {"year": 2024, "amount_eur": "20.00"},
        {"year": 2025, "amount_eur": "30.00"},
    ]
    assert _used(client, bank) == [{"year": 2024, "amount_eur": "5.50"}]


def test_a_platform_with_nothing_entered_lists_no_used_amounts(client, db):
    kraken = _platform(client, "Kraken", "exchange")

    assert _used(client, kraken) == []


def test_any_year_may_be_entered_even_before_the_ledger_begins(client, db):
    """The ledger holds no event at all here, and the record may still be complete."""
    broker = _platform(client)

    assert (
        client.put(
            f"/api/platforms/{broker}/allowance-used/2009", json={"amount_eur": "801.00"}
        ).status_code
        == 204
    )
    assert _used(client, broker) == [{"year": 2009, "amount_eur": "801.00"}]


@pytest.mark.parametrize("amount", ["-0.01", "12.345", "abc"])
def test_a_negative_or_over_precise_amount_is_refused(client, db, amount):
    broker = _platform(client)

    refused = client.put(
        f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": amount}
    )

    assert refused.status_code == 422
    assert _used(client, broker) == []


def test_an_amount_as_a_json_number_is_refused(client, db):
    broker = _platform(client)

    refused = client.put(f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": 12})

    assert refused.status_code == 422


def test_trailing_zeros_past_the_cent_are_not_over_precise(client, db):
    broker = _platform(client)

    stored = client.put(
        f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "12.300"}
    )

    assert stored.status_code == 204
    assert _used(client, broker) == [{"year": 2025, "amount_eur": "12.30"}]


def test_an_unknown_platform_answers_not_found(client, db):
    assert (
        client.put("/api/platforms/12345/allowance-used/2025", json={"amount_eur": "1.00"})
    ).status_code == 404
    assert client.delete("/api/platforms/12345/allowance-used/2025").status_code == 404


@pytest.mark.parametrize("kind", ["exchange", "cold_storage", "software_wallet"])
def test_a_platform_that_cannot_withhold_is_refused_with_a_reason(client, db, kind):
    platform_id = _platform(client, "Somewhere", kind)

    stored = client.put(
        f"/api/platforms/{platform_id}/allowance-used/2025", json={"amount_eur": "1.00"}
    )
    cleared = client.delete(f"/api/platforms/{platform_id}/allowance-used/2025")

    for refused in (stored, cleared):
        assert refused.status_code == 409
        assert "broker or bank" in refused.json()["detail"]
    assert _used(client, platform_id) == []


def test_a_bank_records_a_used_amount_like_a_broker(client, db):
    """A savings bank the ledger does not otherwise track holds its exemption
    order's figure with no Account under it."""
    bank = _platform(client, "Sparkasse", "bank")

    stored = client.put(f"/api/platforms/{bank}/allowance-used/2025", json={"amount_eur": "50.00"})

    assert stored.status_code == 204
    assert _used(client, bank) == [{"year": 2025, "amount_eur": "50.00"}]


def test_used_amounts_survive_a_change_of_withholding_and_can_still_be_entered(client, db):
    """A past year's certificate stays true after the broker stops withholding,
    and a status change does not lock the Admin out of the history."""
    broker = _platform(client)
    client.put(
        f"/api/platforms/{broker}/withholding",
        json={"behaviour": "at_source", "exemption_order_eur": "1000"},
    )
    client.put(f"/api/platforms/{broker}/allowance-used/2024", json={"amount_eur": "640.00"})

    changed = client.put(f"/api/platforms/{broker}/withholding", json={"behaviour": "none"})
    entered = client.put(
        f"/api/platforms/{broker}/allowance-used/2023", json={"amount_eur": "310.00"}
    )

    assert changed.status_code == 204
    assert entered.status_code == 204
    assert _used(client, broker) == [
        {"year": 2023, "amount_eur": "310.00"},
        {"year": 2024, "amount_eur": "640.00"},
    ]


def test_the_lodged_order_is_untouched_by_a_used_amount(client, db):
    """What was lodged and what was used are two facts; entering one leaves
    the other as it stood."""
    broker = _platform(client)
    client.put(
        f"/api/platforms/{broker}/withholding",
        json={"behaviour": "at_source", "exemption_order_eur": "1000"},
    )

    client.put(f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "640.00"})

    (platform,) = client.get("/api/platforms").json()
    assert platform["exemption_order_eur"] == "1000"


def test_a_platform_holding_used_amounts_refuses_removal_until_they_are_cleared(client, db):
    broker = _platform(client)
    for year in ("2023", "2024"):
        client.put(f"/api/platforms/{broker}/allowance-used/{year}", json={"amount_eur": "1.00"})

    refused = client.delete(f"/api/platforms/{broker}")

    assert refused.status_code == 409
    reason = refused.json()["detail"]
    assert reason == "This Platform still holds an allowance used at source — remove it first."
    assert not any(character.isdigit() for character in reason)
    assert _used(client, broker) != []

    for year in ("2023", "2024"):
        client.delete(f"/api/platforms/{broker}/allowance-used/{year}")
    assert client.delete(f"/api/platforms/{broker}").status_code == 204
    assert client.get("/api/platforms").json() == []


def test_a_removal_refused_for_an_account_and_used_amounts_names_both(client, db):
    broker = _platform(client)
    client.post(f"/api/platforms/{broker}/accounts", json={"name": "Depot"})
    client.put(f"/api/platforms/{broker}/allowance-used/2025", json={"amount_eur": "1.00"})

    refused = client.delete(f"/api/platforms/{broker}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Platform still holds the Account 'Depot' and an allowance used at source"
        " — remove them first."
    )
