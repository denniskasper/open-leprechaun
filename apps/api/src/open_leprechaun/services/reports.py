"""The report lifecycle (ticket 23). Generating a report is the Admin's
explicit act: it computes the year's figures — §23 disposals (21), §22
income (22) and the §20 category balances (26) — freezes them as JSON on a
new report row, and stamps the
fingerprint of the inputs that produced them (ADR-0014) under the report's
own subject. The frozen figures are what every read answers, verbatim: a
report is never recomputed, silently or otherwise — regenerating is a new
report, and a final report never changes at all.

Staleness is the fingerprint's answer, not a recomputation: a report whose
stored fingerprint no longer matches the current inputs is flagged stale
wherever it is shown, and the notice names what moved by input class and
count — the same comparison that guards the Tax Lot materialisation
(repositories/fingerprints.drifted), deliberately shared, never duplicated.
The fingerprint covers statutory configuration, so correcting a rate marks
every report resting on it stale while no transaction has moved; deleting a
transaction a report depends on likewise marks it stale — the frozen figures
stand, and the mismatch says the ground moved underneath them.

The stamp must describe exactly the ledger the figures saw. The engines read
on their own snapshots — and a valuation may fetch rates mid-computation —
so generation brackets them: the fingerprint taken before must still be the
fingerprint at the instant the report and its stamp land, in one
transaction, or the generation refuses rather than stamping a fingerprint
the figures may not have seen. (The rate store itself is append-only and
immutable, ADR-0017, so a fetch drifts nothing.)

Money crosses into the frozen JSON as fixed-point decimal strings and
instants as ISO-8601 — never a float — so the figures served years later are
byte-for-byte what generation computed.
"""

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Connection, Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import fingerprints, reports
from open_leprechaun.repositories.reports import Refusal
from open_leprechaun.services import lots, preflight, section20, section22, section23

__all__ = ["Blocked", "GenerationRacedError", "detail", "finalise", "generate", "overview"]


class GenerationRacedError(Exception):
    """The inputs moved while the figures were being computed — the report
    was not stored, because its stamp would describe a ledger the figures
    never saw. Generating again reads the settled state."""

    def __init__(self) -> None:
        super().__init__(
            "The ledger or configuration changed while the report was being"
            " generated — nothing was stored. Generate again."
        )


@dataclass(frozen=True)
class ReportOverview:
    """One report as a listing shows it: the lifecycle row and the staleness
    verdict — empty `changed_inputs` means the frozen figures still rest on
    exactly the inputs that produced them."""

    id: int
    year: int
    status: str
    generated_at: datetime
    finalised_at: datetime | None
    stale: bool
    changed_inputs: tuple[fingerprints.DriftedInput, ...]
    # The pre-flight override (ticket 25), where finalisation was one: the
    # acknowledgement verbatim and the blockers it overrode as stored —
    # frozen record, answered wherever the report is shown.
    override_acknowledgement: str | None
    overridden_blockers: list[dict] | None


@dataclass(frozen=True)
class ReportDetail(ReportOverview):
    """A report with its frozen figures, exactly as generation stored them."""

    figures: dict


def generate(engine: Engine, source: ReferenceRateSource, *, year: int) -> int:
    """Compute the year's figures, freeze them on a new draft report, and
    stamp the fingerprint of the inputs that produced them — never mutating
    any existing report, however many the year already has."""
    with lots.snapshot(engine) as connection:
        before = fingerprints.current(connection)
    figures = {
        "section23": _frozen(section23.year_report(engine, source, year=year)),
        "section22": _frozen(section22.year_report(engine, source, year=year)),
        "section20": _frozen(section20.year_report(engine, source, year=year)),
    }
    with lots.snapshot(engine) as connection:
        current = fingerprints.current(connection)
        if current != before:
            raise GenerationRacedError
        report_id = reports.create(connection, year=year, figures=figures)
        fingerprints.record(connection, _subject(report_id), current)
    return report_id


def overview(engine: Engine) -> list[ReportOverview]:
    """Every report, newest first, each wearing its staleness verdict — one
    snapshot, so every verdict describes the same instant of the inputs."""
    with lots.snapshot(engine) as connection:
        rows = reports.list_reports(connection)
        if not rows:
            return []
        current = fingerprints.current(connection)
        return [
            ReportOverview(**_lifecycle(row, _changed(connection, row.id, current))) for row in rows
        ]


def detail(engine: Engine, report_id: int) -> ReportDetail | None:
    """One report with its frozen figures — answered as stored, never
    recomputed — and its staleness verdict on the same snapshot."""
    with lots.snapshot(engine) as connection:
        row = reports.get(connection, report_id)
        if row is None:
            return None
        current = fingerprints.current(connection)
        return ReportDetail(
            **_lifecycle(row, _changed(connection, row.id, current)), figures=row.figures
        )


@dataclass(frozen=True)
class Blocked:
    """Finalisation refused: the pre-flight blockers (ticket 25) standing
    open for the report's year, each linking the screen that resolves it."""

    blockers: tuple[preflight.Blocker, ...]


def finalise(
    engine: Engine, report_id: int, *, acknowledgement: str | None = None
) -> Refusal | Blocked | None:
    """Draft → final, the one transition a report ever makes — refused while
    any pre-flight blocker stands open for the report's year (ticket 25).
    An acknowledgement overrides the blockers, and the override is recorded
    on the report itself: what was acknowledged, over which objections. An
    acknowledgement offered where nothing blocks overrides nothing.

    The checks read the present, then the flip lands in its own transaction:
    a ledger edit slipped between the two could finalise past a blocker it
    just created — accepted as negligible on a single-Admin instance, the
    same judgement generation makes of its ABA window, and the staleness
    verdict still names whatever moved."""
    with engine.connect() as connection:
        row = reports.get(connection, report_id)
    if row is None:
        return Refusal.no_such_report
    if row.status == "final":
        return Refusal.already_final
    found = preflight.blockers(engine, year=row.year)
    if found and acknowledgement is None:
        return Blocked(blockers=found)
    with engine.begin() as connection:
        return reports.finalise(
            connection,
            report_id,
            override_acknowledgement=acknowledgement if found else None,
            overridden_blockers=[asdict(blocker) for blocker in found] if found else None,
        )


def _subject(report_id: int) -> str:
    """The report's name in the input_fingerprint table, beside the
    materialisation subjects."""
    return f"report:{report_id}"


def _changed(
    connection: Connection, report_id: int, current: dict[str, fingerprints.InputDigest]
) -> tuple[fingerprints.DriftedInput, ...]:
    stored = fingerprints.stored(connection, _subject(report_id))
    return tuple(fingerprints.drifted(stored, current))


def _lifecycle(row: Row, changed: tuple[fingerprints.DriftedInput, ...]) -> dict:
    return {
        "id": row.id,
        "year": row.year,
        "status": row.status,
        "generated_at": row.generated_at,
        "finalised_at": row.finalised_at,
        "stale": bool(changed),
        "changed_inputs": changed,
        "override_acknowledgement": row.override_acknowledgement,
        "overridden_blockers": row.overridden_blockers,
    }


def _frozen(value: object) -> object:
    """A figure as it crosses into the frozen JSON: dataclasses as objects,
    money and quantities as fixed-point decimal strings, instants as
    ISO-8601 — reversible and float-free in both directions."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _frozen(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_frozen(item) for item in value]
    return value
