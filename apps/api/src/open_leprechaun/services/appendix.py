"""The appendix behind a report's headline figures (ticket 24): every figure
backed by the line items that produced it, exportable as CSV and as PDF.

Both exports render one `Appendix` — every cell and every summary value is a
string formatted exactly once here — so the two forms cannot disagree: they
are two renderings of the same strings. The appendix is built from the
report's **frozen figures**, never recomputed, so a final report's appendix
is as immutable as the report; only the labels (an Instrument's symbol, an
Account's name) are resolved at export time, presentation over the frozen
identity, never a figure.

The lines are one row per record that produced a figure. A §23 disposal
appears as one row per consumed lot slice — the disposal's rows are its
lots, each showing acquisition and disposal dates, quantity, basis,
proceeds, its share of the fees, holding period and whether it is exempt or
taxable; a slice resting on an Opening Balance estimate is marked, and the
summary states how much of the counted gain rests on estimation. Exempt
disposals stand in full while the totals exclude them — visible working,
correct figure. §22 receipts and §20 events are one row each, wearing their
own category.

Euro amounts are stated in cents at this presentation boundary — the one
rounding rule (services/rounding); quantities pass through verbatim. A
figure the frozen report carries as null is stated as awaiting valuation,
never as a number.
"""

import csv
import io
from dataclasses import astuple, dataclass, fields
from datetime import datetime
from decimal import Decimal

from fpdf import FPDF
from sqlalchemy import Engine

from open_leprechaun.repositories import holdings as holdings_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import fx, lots, reports
from open_leprechaun.services.rounding import cents
from open_leprechaun.services.section23 import counts

__all__ = ["Appendix", "Line", "assemble", "build", "csv_export", "pdf_export"]


@dataclass(frozen=True)
class Line:
    """One line of the appendix, every value a formatted string. `amount_eur`
    is what the line put toward its section's figure — a §23 gain, a §22
    market value on receipt, a §20 counted amount — and `treatment` says
    whether it counts. A field a section has nothing to say for stays
    empty."""

    section: str
    line: str
    category: str
    instrument: str = ""
    account: str = ""
    acquired_on: str = ""
    date: str = ""
    quantity: str = ""
    basis_eur: str = ""
    proceeds_eur: str = ""
    fees_eur: str = ""
    amount_eur: str = ""
    holding_days: str = ""
    treatment: str = ""
    estimated_basis: str = ""


COLUMNS = tuple(field.name for field in fields(Line))
"""The export header, straight from the Line shape — a column can never
drift from the cells beneath it."""

AWAITING = "awaiting valuation"
"""How a figure the frozen report carries as null is stated — the condition,
never a guessed number."""

ESTIMATED = "estimated"
"""The mark on a line whose basis rests on an Opening Balance estimate."""


@dataclass(frozen=True)
class Appendix:
    """One report's appendix, every value already formatted for export: the
    summary as (label, value) pairs — the headline figures the lines back —
    and the lines under COLUMNS. CSV and PDF both render exactly this."""

    report_id: int
    year: int
    status: str
    summary: tuple[tuple[str, str], ...]
    lines: tuple[tuple[str, ...], ...]


def assemble(engine: Engine, report_id: int) -> Appendix | None:
    """The stored report's appendix — frozen figures, labels resolved at
    export time on one snapshot."""
    report = reports.detail(engine, report_id)
    if report is None:
        return None
    with lots.snapshot(engine) as connection:
        instrument_rows = lots_repository.instrument_rows(connection)
        account_rows = holdings_repository.account_rows(connection)
    instruments = {row.id: row.symbol for row in instrument_rows}
    accounts = {row.id: f"{row.platform_name} / {row.name}" for row in account_rows}
    return build(report, instruments=instruments, accounts=accounts)


def build(
    report: reports.ReportDetail, *, instruments: dict[int, str], accounts: dict[int, str]
) -> Appendix:
    """The appendix of a report's frozen figures. Label maps translate the
    frozen ids for presentation; an id no longer resolvable keeps its frozen
    identity as `instrument:7` — the figure stands even where the label
    moved on. Reads the shape generation writes as of ticket 24 — a
    consumption states its fee share — and fails loudly on an older frozen
    report rather than rendering a silently thinner line; pre-release, such
    a report is regenerated, not migrated."""
    lines = [
        *_section23_lines(report.figures["section23"], instruments, accounts),
        *_section22_lines(report.figures["section22"], instruments, accounts),
        *_section20_lines(report.figures["section20"]),
    ]
    return Appendix(
        report_id=report.id,
        year=report.year,
        status=report.status,
        summary=tuple(_summary(report)),
        lines=tuple(astuple(line) for line in lines),
    )


def csv_export(appendix: Appendix) -> str:
    """The machine-readable form: the summary as label,value rows, a blank
    row, then the line-item table under its header."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows(appendix.summary)
    writer.writerow([])
    writer.writerow(COLUMNS)
    writer.writerows(appendix.lines)
    return out.getvalue()


def pdf_export(appendix: Appendix) -> bytes:
    """The archival form: the same summary and the same lines, rendered to
    landscape A4."""
    pdf = FPDF(orientation="landscape", format="A4")
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_margin(10)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    title = f"Report {appendix.report_id} — {appendix.year} ({appendix.status}) — appendix"
    pdf.cell(text=_latin(title), new_x="LMARGIN", new_y="NEXT", h=8)
    pdf.set_font(size=7)
    with pdf.table(width=120, align="LEFT", first_row_as_headings=False) as table:
        for label, value in appendix.summary:
            row = table.row()
            row.cell(_latin(label))
            row.cell(_latin(value))
    pdf.ln(4)
    pdf.set_font(size=6)
    with pdf.table() as table:
        header = table.row()
        for column in COLUMNS:
            header.cell(column)
        for line in appendix.lines:
            row = table.row()
            for cell in line:
                row.cell(_latin(cell))
    return bytes(pdf.output())


def _latin(text: str) -> str:
    """The text as the PDF's core font can carry it: cp1252, a character
    beyond it replaced. Only labels can hold such a character — every figure
    is digits — so a replacement never touches a number."""
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _summary(report: reports.ReportDetail) -> list[tuple[str, str]]:
    section23 = report.figures["section23"]
    section22 = report.figures["section22"]
    section20 = report.figures["section20"]
    entries = [
        ("report", str(report.id)),
        ("year", str(report.year)),
        ("status", report.status),
        ("section23.total_gain_eur", _amount(section23["total_gain_eur"])),
        ("section23.gain_on_estimated_basis_eur", _estimated_exposure(section23)),
        *_freigrenze(section23["freigrenze"], "section23", "taxable_gain_eur"),
        ("section22.total_income_eur", _amount(section22["total_income_eur"])),
        *_freigrenze(section22["freigrenze"], "section22", "taxable_income_eur"),
    ]
    for balance in section20["balances"] or []:
        entries.append(
            (f"section20.balance.{balance['category']}_eur", _amount(balance["balance_eur"]))
        )
    assessment = section20["assessment"]
    if assessment is None:
        entries.append(("section20.taxable_eur", AWAITING))
    else:
        entries.extend(
            [
                ("section20.combined_eur", _amount(assessment["combined_eur"])),
                ("section20.allowance_applied_eur", _amount(assessment["allowance_applied_eur"])),
                ("section20.taxable_eur", _amount(assessment["taxable_eur"])),
                ("section20.tax_total_eur", _amount(assessment["tax"]["total_eur"])),
            ]
        )
    return entries


def _freigrenze(verdict: dict | None, section: str, taxable_key: str) -> list[tuple[str, str]]:
    """The all-or-nothing verdict's summary lines — awaiting where the year
    could state none."""
    if verdict is None:
        return [(f"{section}.tax_free", AWAITING), (f"{section}.{taxable_key}", AWAITING)]
    return [
        (f"{section}.freigrenze_limit_eur", _amount(verdict["limit_eur"])),
        (f"{section}.tax_free", "yes" if verdict["tax_free"] else "no"),
        (f"{section}.{taxable_key}", _amount(verdict[taxable_key])),
    ]


def _estimated_exposure(figures: dict) -> str:
    """How much of the counted gain rests on an estimated basis: the exact
    frozen gains of counting estimate-based slices, summed, then stated by
    the presentation rule — the engine's own counting rule
    (section23.counts) applied to the frozen facts, so an exempt estimated
    line wears its mark while exposing nothing the headline counted.
    Awaiting while any counted gain is unstated — the exposure cannot be
    totalled around a missing member."""
    if figures["total_gain_eur"] is None:
        return AWAITING
    exposed = sum(
        (
            Decimal(consumption["gain_eur"])
            for disposal in figures["disposals"]
            for consumption in disposal["consumptions"]
            if counts(long_term=consumption["long_term"], basis_source=consumption["basis_source"])
            and consumption["basis_source"] == lots.ESTIMATE
        ),
        Decimal(0),
    )
    return _amount(format(exposed, "f"))


def _section23_lines(
    figures: dict, instruments: dict[int, str], accounts: dict[int, str]
) -> list[Line]:
    return [
        Line(
            section="section23",
            line=f"leg:{disposal['leg_id']}",
            category="private_sale",
            instrument=_label(instruments, disposal["instrument_id"], "instrument"),
            account=_label(accounts, disposal["account_id"], "account"),
            acquired_on=_date(consumption["acquired_at"]),
            date=_date(disposal["disposed_at"]),
            quantity=consumption["quantity"],
            basis_eur=_amount(consumption["basis_eur"], absent=""),
            proceeds_eur=_amount(consumption["proceeds_eur"], absent=""),
            fees_eur=_amount(consumption["costs_eur"], absent=""),
            amount_eur=_amount(consumption["gain_eur"], absent=""),
            holding_days=str(consumption["holding_days"]),
            treatment=_treatment(consumption),
            estimated_basis=ESTIMATED if consumption["basis_source"] == lots.ESTIMATE else "",
        )
        for disposal in figures["disposals"]
        for consumption in disposal["consumptions"]
    ]


def _treatment(consumption: dict) -> str:
    if consumption["basis_source"] == lots.WITHOUT_CONSIDERATION:
        return "outside_section23"
    if consumption["long_term"]:
        return "exempt"
    if consumption["gain_eur"] is None:
        return "awaiting_valuation"
    return "taxable"


def _section22_lines(
    figures: dict, instruments: dict[int, str], accounts: dict[int, str]
) -> list[Line]:
    return [
        Line(
            section="section22",
            line=f"leg:{income['leg_id']}",
            category=income["type"],
            instrument=_label(instruments, income["instrument_id"], "instrument"),
            account=_label(accounts, income["account_id"], "account"),
            date=_date(income["received_at"]),
            quantity=income["quantity"],
            amount_eur=_amount(income["market_value_eur"], absent=""),
            treatment="awaiting_valuation" if income["market_value_eur"] is None else "counted",
        )
        for income in figures["incomes"]
    ]


def _section20_lines(figures: dict) -> list[Line]:
    """One row per Section 20 Event as its pot counted it. The frozen entry
    names its producing record (`source`) rather than an Instrument or
    Account — the event shape's own vocabulary (ADR-0013)."""
    return [
        Line(
            section="section20",
            line=entry["event"]["source"],
            category=balance["category"],
            date=entry["event"]["date"],
            amount_eur=_amount(entry["counted_eur"]),
            treatment="counted",
        )
        for balance in figures["balances"] or []
        for entry in balance["entries"]
    ]


def _amount(frozen: str | None, *, absent: str = AWAITING) -> str:
    """A frozen euro amount at the presentation boundary: cents, half-even —
    the one rounding rule (services/rounding)."""
    if frozen is None:
        return absent
    return format(cents(Decimal(frozen)), "f")


def _date(frozen: str) -> str:
    """The Europe/Berlin calendar date of a frozen instant — the same clock
    that buckets tax years."""
    return fx.event_date(datetime.fromisoformat(frozen)).isoformat()


def _label(labels: dict[int, str], key: int, kind: str) -> str:
    return labels.get(key, f"{kind}:{key}")
