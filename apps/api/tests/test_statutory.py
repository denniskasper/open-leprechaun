"""The statutory configuration store (ticket 09): every constant the tax
engines will need lives as per-year data with a cited source, editable in
settings — so no later ticket ever hardcodes one.

The seams are the schema over real Postgres, the repository, the service that
answers the questions later tickets must ask it (which required values a year
is missing, which variant an election selects, whether an entry is valid),
and the HTTP endpoints.

Mutating tests work on years no migration seeds (2030+) through the `store`
fixture, which wipes those years and restores the default election — so the
migration-carried rows stay pristine for the tests that assert them, and the
file holds across repeated runs against the same database.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import statutory
from open_leprechaun.services import statutory as statutory_service


@pytest.fixture
def store(db):
    """The migrated database with this file's mutation years wiped and the
    election back at its default — statutory rows outlive the shared `db`
    fixture, which resets only the ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
        connection.execute(
            text("UPDATE tax_election SET filing_status = 'single', church_tax = 'none'")
        )
    return db


def _insert_value(store, *, year, key, value, source="a cited source"):
    with store.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO statutory_value (year, key, value, source)"
                " VALUES (:year, :key, :value, :source)"
            ),
            {"year": year, "key": key, "value": value, "source": source},
        )


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_refuses_a_key_outside_the_vocabulary(store):
    with pytest.raises(IntegrityError):
        _insert_value(store, year=2031, key="coffee_deduction", value=Decimal("100"))


def test_the_schema_refuses_a_negative_value(store):
    with pytest.raises(IntegrityError):
        _insert_value(store, year=2031, key="saver_allowance_single", value=Decimal("-1"))


def test_the_schema_refuses_a_rate_above_one(store):
    """A flat rate of 25 would be a percentage stored where a fraction
    belongs — refused at the schema, so the mistake cannot wait for a tax
    figure to reveal it. An amount in EUR may of course exceed one."""
    with pytest.raises(IntegrityError):
        _insert_value(store, year=2031, key="flat_rate", value=Decimal("25"))
    _insert_value(store, year=2031, key="loss_cap_termingeschaefte", value=Decimal("20000"))


def test_the_schema_accepts_an_opening_carryforward(store):
    """Ticket 27: a loss carryforward established by an assessment predating
    the ledger enters as per-year configuration — the vocabulary knows one
    per §20 category."""
    for category in ("aktien", "sonstige", "termingeschaefte"):
        _insert_value(store, year=2031, key=f"opening_carryforward_{category}", value=Decimal("5"))


def test_the_schema_refuses_a_blank_source(store):
    """Each value records where it came from — a citation is not optional."""
    with pytest.raises(IntegrityError):
        _insert_value(store, year=2031, key="flat_rate", value=Decimal("0.25"), source="   ")


def test_the_schema_refuses_a_year_outside_the_regime(store):
    """The store begins with the Abgeltungsteuer era (2009); an earlier year
    is a typo, not history this application computes."""
    for year in (2008, 2101):
        with pytest.raises(IntegrityError):
            _insert_value(store, year=year, key="flat_rate", value=Decimal("0.25"))


def test_the_schema_holds_one_value_per_year_and_key(store):
    _insert_value(store, year=2031, key="flat_rate", value=Decimal("0.25"))
    with pytest.raises(IntegrityError):
        _insert_value(store, year=2031, key="flat_rate", value=Decimal("0.3"))


def test_the_schema_holds_the_election_to_one_row(store):
    with pytest.raises(IntegrityError), store.begin() as connection:
        connection.execute(text("INSERT INTO tax_election (filing_status) VALUES ('single')"))


def test_the_schema_refuses_an_election_outside_the_vocabulary(store):
    for column, impostor in (("filing_status", "widowed"), ("church_tax", "ten_percent")):
        with pytest.raises(IntegrityError), store.begin() as connection:
            connection.execute(
                text(f"UPDATE tax_election SET {column} = :impostor"),
                {"impostor": impostor},
            )


# --- The migration carries the known values ---------------------------------


def test_a_fresh_database_knows_the_statutory_values_for_the_deliverable_era(fresh_db):
    """2024-2026 arrive with the schema, each with its source — a deployment
    can compute the first deliverable (the 2026 return) without anyone
    re-entering public law. Spot checks against the statutes and the BMF
    letters, not against the migration's own table."""
    with fresh_db.connect() as connection:
        rows = {
            (row.year, row.key): (row.value, row.source)
            for row in connection.execute(
                text("SELECT year, key, value, source FROM statutory_value")
            )
        }

    assert rows[(2026, "private_sale_exemption_limit")][0] == Decimal("1000")
    assert rows[(2026, "other_income_exemption_limit")][0] == Decimal("256")
    assert rows[(2026, "saver_allowance_single")][0] == Decimal("1000")
    assert rows[(2026, "saver_allowance_joint")][0] == Decimal("2000")
    assert rows[(2026, "flat_rate")][0] == Decimal("0.25")
    assert rows[(2026, "solidarity_surcharge_rate")][0] == Decimal("0.055")
    assert rows[(2026, "church_tax_rate_bavaria_bw")][0] == Decimal("0.08")
    assert rows[(2026, "church_tax_rate_other_laender")][0] == Decimal("0.09")
    # The Basiszins moves every year: 2.29 % (2024), 2.53 % (2025), 3.20 % (2026).
    assert rows[(2024, "advance_lump_sum_base_rate")][0] == Decimal("0.0229")
    assert rows[(2025, "advance_lump_sum_base_rate")][0] == Decimal("0.0253")
    assert rows[(2026, "advance_lump_sum_base_rate")][0] == Decimal("0.0320")
    # Every carried value cites where it came from.
    assert all(source.strip() for _, source in rows.values())
    assert "BMF" in rows[(2026, "advance_lump_sum_base_rate")][1]
    # The §20 Abs. 6 Satz 5/6 loss caps were struck retroactively for all open
    # cases (JStG 2024), so no cap rides in — absence means uncapped. And no
    # opening carryforward rides in either: that is the Admin's own assessment
    # data, never public law.
    assert not any(key.startswith(("loss_cap", "opening_carryforward")) for _, key in rows)


# --- The repository ----------------------------------------------------------


def test_entering_a_value_again_replaces_it_with_its_new_source(store):
    """Correcting a value is the everyday act — a corrected rate arrives with
    the citation that corrected it, and the store holds one truth per year
    and key, never two."""
    statutory.upsert_value(
        store, year=2031, key="flat_rate", value=Decimal("0.25"), source="§ 32d Abs. 1 Satz 1 EStG"
    )
    statutory.upsert_value(
        store, year=2031, key="flat_rate", value=Decimal("0.2"), source="a future amendment"
    )

    (row,) = [r for r in statutory.list_values(store) if r.year == 2031]
    assert row.value == Decimal("0.2")
    assert row.source == "a future amendment"


def test_unsetting_a_value_removes_it_and_says_when_nothing_was_there(store):
    statutory.upsert_value(
        store, year=2031, key="flat_rate", value=Decimal("0.25"), source="§ 32d EStG"
    )

    assert statutory.delete_value(store, year=2031, key="flat_rate") is True
    assert statutory.delete_value(store, year=2031, key="flat_rate") is False
    assert [r for r in statutory.list_values(store) if r.year == 2031] == []


def test_the_election_is_read_and_changed_as_the_one_row_it_is(store):
    statutory.set_election(store, filing_status="joint", church_tax="other_laender")
    changed = statutory.election(store)
    assert (changed.filing_status, changed.church_tax) == ("joint", "other_laender")

    statutory.set_election(store, filing_status="single", church_tax="none")
    restored = statutory.election(store)
    assert (restored.filing_status, restored.church_tax) == ("single", "none")


def test_a_fresh_database_has_the_default_election(fresh_db):
    """Single filing and no church tax — the row exists from birth, so an
    engine never meets a missing election."""
    with fresh_db.connect() as connection:
        election = connection.execute(
            text("SELECT filing_status, church_tax FROM tax_election")
        ).one()

    assert election.filing_status == "single"
    assert election.church_tax == "none"


# --- The vocabulary and what a complete year requires ------------------------


def test_the_vocabulary_covers_every_constant_the_tax_engines_will_need():
    assert set(statutory_service.KEYS) == {
        "private_sale_exemption_limit",
        "other_income_exemption_limit",
        "saver_allowance_single",
        "saver_allowance_joint",
        "flat_rate",
        "solidarity_surcharge_rate",
        "church_tax_rate_bavaria_bw",
        "church_tax_rate_other_laender",
        "advance_lump_sum_base_rate",
        "loss_cap_aktien",
        "loss_cap_sonstige",
        "loss_cap_termingeschaefte",
        "opening_carryforward_aktien",
        "opening_carryforward_sonstige",
        "opening_carryforward_termingeschaefte",
        "partial_exemption_aktienfonds",
        "partial_exemption_mischfonds",
        "partial_exemption_immobilienfonds",
        "partial_exemption_auslands_immobilienfonds",
        "partial_exemption_sonstige",
    }


def test_every_key_knows_its_unit_and_whether_a_year_requires_it():
    """Amounts are EUR, the rest are fractions of one; only the loss caps and
    the opening carryforwards are optional — an absent cap means uncapped
    (JStG 2024 struck the §20 Abs. 6 Satz 5/6 caps retroactively) and an
    absent opening carryforward means zero, never unknown."""
    keys = statutory_service.KEYS
    rates = {key for key, definition in keys.items() if definition.unit == "rate"}
    optional = {key for key, definition in keys.items() if not definition.required}

    assert rates == {
        "flat_rate",
        "solidarity_surcharge_rate",
        "church_tax_rate_bavaria_bw",
        "church_tax_rate_other_laender",
        "advance_lump_sum_base_rate",
        "partial_exemption_aktienfonds",
        "partial_exemption_mischfonds",
        "partial_exemption_immobilienfonds",
        "partial_exemption_auslands_immobilienfonds",
        "partial_exemption_sonstige",
    }
    assert optional == {
        "loss_cap_aktien",
        "loss_cap_sonstige",
        "loss_cap_termingeschaefte",
        "opening_carryforward_aktien",
        "opening_carryforward_sonstige",
        "opening_carryforward_termingeschaefte",
    }


def test_a_year_with_a_required_value_unset_is_identifiable(store):
    """The question ticket 25 asks before letting a report finalise. An
    absent optional cap never counts as missing."""
    untouched = statutory_service.missing_for_year(store, 2031)
    assert untouched == [key for key, d in statutory_service.KEYS.items() if d.required]

    statutory.upsert_value(store, year=2031, key="flat_rate", value=Decimal("0.25"), source="§ 32d")
    assert "flat_rate" not in statutory_service.missing_for_year(store, 2031)

    # The migration-carried deliverable year is complete out of the box.
    assert statutory_service.missing_for_year(store, 2026) == []


def test_an_optional_value_answers_none_when_unset_and_the_value_when_set(store):
    """How the §20 engine (ticket 26) reads a loss cap: an absent cap means
    uncapped — None, never an error and never a default — while a set one
    answers exactly what the store holds, for that year alone."""
    assert statutory_service.optional_value(store, year=2031, key="loss_cap_aktien") is None

    statutory.upsert_value(
        store, year=2031, key="loss_cap_aktien", value=Decimal("20000"), source="a cited source"
    )
    assert statutory_service.optional_value(store, year=2031, key="loss_cap_aktien") == Decimal(
        "20000"
    )
    assert statutory_service.optional_value(store, year=2032, key="loss_cap_aktien") is None


def test_the_election_selects_which_per_year_values_apply():
    """Filing status picks the saver-allowance variant; the church-tax
    election picks a rate key or no church tax at all. The selection lives
    here so no tax engine ever doubles an amount or picks a rate in logic."""
    assert statutory_service.saver_allowance_key("single") == "saver_allowance_single"
    assert statutory_service.saver_allowance_key("joint") == "saver_allowance_joint"
    assert statutory_service.church_tax_rate_key("none") is None
    assert statutory_service.church_tax_rate_key("bavaria_bw") == "church_tax_rate_bavaria_bw"
    assert statutory_service.church_tax_rate_key("other_laender") == "church_tax_rate_other_laender"


def test_an_entry_outside_its_bounds_is_refused_with_a_sentence():
    ok = statutory_service.entry_defect(year=2031, key="flat_rate", value=Decimal("0.25"))
    assert ok is None
    assert (
        statutory_service.entry_defect(year=2008, key="flat_rate", value=Decimal("0.25"))
        is not None
    )
    assert (
        statutory_service.entry_defect(year=2101, key="flat_rate", value=Decimal("0.25"))
        is not None
    )
    assert (
        statutory_service.entry_defect(year=2031, key="flat_rate", value=Decimal("-0.25"))
        is not None
    )
    # A rate of 25 is a percentage where a fraction belongs.
    assert "0.25" in statutory_service.entry_defect(year=2031, key="flat_rate", value=Decimal("25"))
    # An amount in EUR may of course exceed one.
    assert (
        statutory_service.entry_defect(
            year=2031, key="loss_cap_termingeschaefte", value=Decimal("20000")
        )
        is None
    )


# --- The HTTP seam ----------------------------------------------------------


def test_the_api_lists_the_store_with_sources_election_and_gaps(client, store):
    statutory.upsert_value(
        store,
        year=2031,
        key="advance_lump_sum_base_rate",
        value=Decimal("0.0199"),
        source="BMF-Schreiben v. 02.01.2031",
    )

    answer = client.get("/api/statutory").json()

    assert answer["filing_status"] == "single"
    assert answer["church_tax"] == "none"
    # The vocabulary rides along so the UI never re-declares it.
    keys = {key["key"]: key for key in answer["keys"]}
    assert keys["flat_rate"] == {"key": "flat_rate", "unit": "rate", "required": True}
    assert keys["loss_cap_aktien"]["required"] is False

    newest = answer["years"][0]
    assert newest["year"] == 2031
    (value,) = newest["values"]
    # Fixed-point as a string, never a JSON number.
    assert value == {
        "key": "advance_lump_sum_base_rate",
        "value": "0.0199",
        "source": "BMF-Schreiben v. 02.01.2031",
    }
    assert "flat_rate" in newest["missing"]

    (deliverable,) = [year for year in answer["years"] if year["year"] == 2026]
    assert deliverable["missing"] == []


def test_the_api_enters_and_corrects_a_value(client, store):
    entered = client.put(
        "/api/statutory/values/2031/flat_rate",
        json={"value": "0.25", "source": "§ 32d Abs. 1 Satz 1 EStG"},
    )
    assert entered.status_code == 204

    corrected = client.put(
        "/api/statutory/values/2031/flat_rate",
        json={"value": "0.24", "source": "a future amendment"},
    )
    assert corrected.status_code == 204

    (year_2031,) = [y for y in client.get("/api/statutory").json()["years"] if y["year"] == 2031]
    (value,) = year_2031["values"]
    assert (value["value"], value["source"]) == ("0.24", "a future amendment")


def test_the_api_refuses_what_the_store_cannot_hold(client, store):
    unknown_key = client.put(
        "/api/statutory/values/2031/coffee_deduction",
        json={"value": "1", "source": "wishful thinking"},
    )
    percentage = client.put(
        "/api/statutory/values/2031/flat_rate",
        json={"value": "25", "source": "§ 32d EStG"},
    )
    early = client.put(
        "/api/statutory/values/2008/flat_rate",
        json={"value": "0.25", "source": "§ 32d EStG"},
    )
    blank_source = client.put(
        "/api/statutory/values/2031/flat_rate",
        json={"value": "0.25", "source": "   "},
    )
    as_number = client.put(
        "/api/statutory/values/2031/flat_rate",
        json={"value": 0.25, "source": "§ 32d EStG"},
    )

    assert unknown_key.status_code == 422
    assert percentage.status_code == 422
    assert "0.25" in percentage.json()["detail"]
    assert early.status_code == 422
    assert blank_source.status_code == 422
    assert as_number.status_code == 422
    assert client.get("/api/statutory").json()["years"][0]["year"] == 2026


def test_the_api_unsets_a_value_and_the_gap_reappears(client, store):
    client.put(
        "/api/statutory/values/2031/flat_rate",
        json={"value": "0.25", "source": "§ 32d EStG"},
    )

    removed = client.delete("/api/statutory/values/2031/flat_rate")
    assert removed.status_code == 204
    assert client.delete("/api/statutory/values/2031/flat_rate").status_code == 404
    assert all(year["year"] != 2031 for year in client.get("/api/statutory").json()["years"])


def test_the_api_changes_the_election(client, store):
    changed = client.put(
        "/api/statutory/election",
        json={"filing_status": "joint", "church_tax": "bavaria_bw"},
    )
    assert changed.status_code == 204

    answer = client.get("/api/statutory").json()
    assert answer["filing_status"] == "joint"
    assert answer["church_tax"] == "bavaria_bw"

    outside = client.put(
        "/api/statutory/election",
        json={"filing_status": "widowed", "church_tax": "none"},
    )
    assert outside.status_code == 422


def test_the_api_speaks_the_same_vocabulary_as_the_service():
    from typing import get_args

    from open_leprechaun.routers.statutory import ChurchTax, FilingStatus, StatutoryKey

    assert set(get_args(StatutoryKey)) == set(statutory_service.KEYS)
    assert set(get_args(FilingStatus)) == {"single", "joint"}
    assert set(get_args(ChurchTax)) == {"none", "bavaria_bw", "other_laender"}


def test_the_overview_hands_the_ui_years_newest_first_with_sources_and_gaps(store):
    statutory.upsert_value(
        store, year=2031, key="flat_rate", value=Decimal("0.25"), source="§ 32d Abs. 1 Satz 1 EStG"
    )

    overview = statutory_service.overview(store)

    assert overview.filing_status in ("single", "joint")
    years = [year.year for year in overview.years]
    assert years == sorted(years, reverse=True)
    assert years.index(2031) < years.index(2026)

    (added,) = [year for year in overview.years if year.year == 2031]
    (value,) = added.values
    assert (value.key, value.value, value.source) == (
        "flat_rate",
        Decimal("0.25"),
        "§ 32d Abs. 1 Satz 1 EStG",
    )
    assert "flat_rate" not in added.missing
    assert "saver_allowance_single" in added.missing

    (deliverable,) = [year for year in overview.years if year.year == 2026]
    assert deliverable.missing == ()
    # Values arrive in the vocabulary's own order, ready to render.
    keys_in_order = [value.key for value in deliverable.values]
    assert keys_in_order == [key for key in statutory_service.KEYS if key in set(keys_in_order)]
