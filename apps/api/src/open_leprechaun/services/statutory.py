"""What the application knows about statutory configuration beyond storage
(ticket 09): the key vocabulary with each key's unit and whether a complete
year requires it, and the answers later tickets must ask this module for —
which required values a year is missing (ticket 25 refuses to finalise over
a gap), and which per-year values the Admin's elections select (so no tax
engine ever doubles an allowance or picks a church-tax rate in logic).

`required_value` is how a tax engine (21, 22) reads its per-year limit — and
how a year whose value is unset refuses by name instead of defaulting.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import statutory

FIRST_YEAR = 2009
"""The Abgeltungsteuer era — the earliest regime these engines implement.
The schema holds the same bound; a CHECK and this constant are held to each
other by the schema refusing what entry_defect refuses."""

LAST_YEAR = 2100


@dataclass(frozen=True)
class KeyDefinition:
    """One statutory constant: its unit, and whether a year is incomplete
    without it. A rate is a fraction of one, never a percentage."""

    unit: str  # "eur" | "rate"
    required: bool = True


_RATE = KeyDefinition(unit="rate")
_AMOUNT = KeyDefinition(unit="eur")
# The §20 Abs. 6 Satz 5/6 loss caps were struck retroactively for all open
# cases (JStG 2024, BGBl. 2024 I Nr. 387): an absent cap means uncapped,
# never unknown — so no year requires one.
_OPTIONAL_CAP = KeyDefinition(unit="eur", required=False)
# An opening loss carryforward from an assessment predating the ledger
# (ticket 27): absent means zero, never unknown — so no year requires one.
_OPTIONAL_OPENING = KeyDefinition(unit="eur", required=False)

KEYS: Mapping[str, KeyDefinition] = {
    # The §23 Abs. 3 Satz 5 EStG Freigrenze on private sales.
    "private_sale_exemption_limit": _AMOUNT,
    # The §22 Nr. 3 Satz 2 EStG Freigrenze on Sonstige Einkünfte.
    "other_income_exemption_limit": _AMOUNT,
    # The Sparerpauschbetrag (§20 Abs. 9 EStG), one variant per filing
    # status — the election selects, nothing doubles.
    "saver_allowance_single": _AMOUNT,
    "saver_allowance_joint": _AMOUNT,
    # The Abgeltungsteuer components (§32d EStG, SolzG 1995, KiStG der
    # Länder) — the church-tax election selects a rate key or none.
    "flat_rate": _RATE,
    "solidarity_surcharge_rate": _RATE,
    "church_tax_rate_bavaria_bw": _RATE,
    "church_tax_rate_other_laender": _RATE,
    # The Basiszins driving the Vorabpauschale (§18 Abs. 4 InvStG),
    # published each January for the year just begun.
    "advance_lump_sum_base_rate": _RATE,
    # Per-category loss caps for the §20 engine (ticket 26).
    "loss_cap_aktien": _OPTIONAL_CAP,
    "loss_cap_sonstige": _OPTIONAL_CAP,
    "loss_cap_termingeschaefte": _OPTIONAL_CAP,
    # Per-category opening loss carryforwards, the balance a §20 pot opens
    # the entered year with — from a Verlustfeststellung predating the
    # ledger (ticket 27), the one personal figure this store holds.
    "opening_carryforward_aktien": _OPTIONAL_OPENING,
    "opening_carryforward_sonstige": _OPTIONAL_OPENING,
    "opening_carryforward_termingeschaefte": _OPTIONAL_OPENING,
}


def missing_for_year(engine: Engine, year: int) -> list[str]:
    """The required values this year has no row for, in the vocabulary's
    order — the question ticket 25 asks before letting a report finalise,
    empty when the year is complete."""
    present = {row.key for row in statutory.list_values(engine) if row.year == year}
    return _missing(present)


def _missing(present: set[str]) -> list[str]:
    return [key for key, definition in KEYS.items() if definition.required and key not in present]


def saver_allowance_key(filing_status: str) -> str:
    """Which Sparerpauschbetrag variant the filing status selects."""
    return {"single": "saver_allowance_single", "joint": "saver_allowance_joint"}[filing_status]


def church_tax_rate_key(church_tax: str) -> str | None:
    """Which church-tax rate the election selects — None where none is
    elected, so an engine reads no rate rather than a zero one."""
    return {
        "none": None,
        "bavaria_bw": "church_tax_rate_bavaria_bw",
        "other_laender": "church_tax_rate_other_laender",
    }[church_tax]


class StatutoryValueUnsetError(Exception):
    """The year has no value for a statutory key an engine needs — the engine
    refuses to compute rather than assuming one."""


def required_value(engine: Engine, *, year: int, key: str, statute: str) -> Decimal:
    """The year's value for one key, read from the store — the tax engines'
    (21, 22) one way to a limit, so no constant can hide in logic. A year
    whose value is unset refuses by name: an unset statute is Admin-fixable
    configuration, unlike a valuation nothing can state yet."""
    value = _stored_value(engine, year=year, key=key)
    if value is None:
        raise StatutoryValueUnsetError(
            f"The {year} value for {key} ({statute}) is unset —"
            " enter it in the statutory settings before computing this year."
        )
    return value


def optional_value(engine: Engine, *, year: int, key: str) -> Decimal | None:
    """The year's value for a key no year requires — how the §20 engine
    (ticket 26) reads a loss cap, where absence means uncapped, never
    unknown, so nothing refuses and nothing defaults."""
    return _stored_value(engine, year=year, key=key)


def optional_values(engine: Engine, *, key: str) -> dict[int, Decimal]:
    """Every year's value for a key no year requires, keyed by year — how
    the §20 engine (ticket 27) reads loss caps and opening carryforwards
    across a chain of years in one read."""
    return {row.year: row.value for row in statutory.list_values(engine) if row.key == key}


def _stored_value(engine: Engine, *, year: int, key: str) -> Decimal | None:
    for row in statutory.list_values(engine):
        if row.year == year and row.key == key:
            return row.value
    return None


def entry_defect(*, year: int, key: str, value: Decimal) -> str | None:
    """The sentence naming why this entry cannot be stored, or None when it
    can. Judged before anything is written, mirroring what the schema would
    refuse — so the Admin reads a reason, never a constraint name."""
    if not FIRST_YEAR <= year <= LAST_YEAR:
        return (
            f"Statutory configuration covers {FIRST_YEAR} through {LAST_YEAR} —"
            " the Abgeltungsteuer era these engines implement."
        )
    if value < 0:
        return "A statutory value is never negative."
    if KEYS[key].unit == "rate" and value > 1:
        return "A rate is a fraction of one — 25 % is entered as 0.25."
    return None


@dataclass(frozen=True)
class StatutoryValue:
    key: str
    value: Decimal
    source: str


@dataclass(frozen=True)
class YearOverview:
    year: int
    values: tuple[StatutoryValue, ...]
    # The required keys this year still has no value for.
    missing: tuple[str, ...]


@dataclass(frozen=True)
class StatutoryOverview:
    filing_status: str
    church_tax: str
    years: tuple[YearOverview, ...]


def overview(engine: Engine) -> StatutoryOverview:
    """Everything the settings screen shows: the election, and each year
    newest first with its values in the vocabulary's order and its gaps."""
    order = {key: position for position, key in enumerate(KEYS)}
    values_of: dict[int, list[StatutoryValue]] = {}
    for row in statutory.list_values(engine):
        values_of.setdefault(row.year, []).append(
            StatutoryValue(key=row.key, value=row.value, source=row.source)
        )
    election = statutory.election(engine)
    return StatutoryOverview(
        filing_status=election.filing_status,
        church_tax=election.church_tax,
        years=tuple(
            YearOverview(
                year=year,
                values=tuple(sorted(values, key=lambda value: order[value.key])),
                missing=tuple(_missing({value.key for value in values})),
            )
            for year, values in sorted(values_of.items(), reverse=True)
        ),
    )
