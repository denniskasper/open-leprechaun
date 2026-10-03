"""Report sections shaped like the tax forms (ticket 51): the year's figures
laid out the way the German forms are — Anlage SO for Leistungen and private
sales, Anlage KAP for capital income, Anlage KAP-INV for fund income not
taxed at source — so transcription is mechanical rather than interpretive.

Nothing here computes tax. The engines (services/section22, section23,
section20) have already decided every figure; this module only says where
each one belongs on the return, and how sure that is:

- **unambiguous** — the figure belongs on exactly one line of the year's
  form;
- **ambiguous** — the form offers more than one line and the application
  holds no fact that decides between them; the note says what would;
- **unmapped** — no line numbers are recorded for the year. Line numbers
  move between years, so they are a year-keyed table read from each year's
  official form (docs/research/tax-form-lines.md), never carried over: an
  unmapped year names the form and the field and says the number is missing.

The sections are built at generation and frozen with the report's figures,
so a final report's form lines are as immutable as its amounts.
"""

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass, replace
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import capital_income as capital_income_repository
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.repositories.instruments import FUND_TYPES
from open_leprechaun.services import lots
from open_leprechaun.services.section20 import FUTURES_CATEGORY, Section20Year, creditable_eur
from open_leprechaun.services.section22 import Section22Year
from open_leprechaun.services.section23 import Consumption, Section23Year, counts
from open_leprechaun.services.security_disposals import PARTIAL_EXEMPTION_STATUTES, SHARE_CATEGORY

__all__ = [
    "AMBIGUOUS",
    "LAYOUTS",
    "TO_DECLARE",
    "UNAMBIGUOUS",
    "UNMAPPED",
    "WITHHELD_AT_SOURCE",
    "Balance",
    "Field",
    "FormLine",
    "FormSection",
    "TaxForms",
    "TaxStatement",
    "build",
    "year_forms",
]

UNAMBIGUOUS = "unambiguous"
AMBIGUOUS = "ambiguous"
UNMAPPED = "unmapped"

TO_DECLARE = "to_declare"
WITHHELD_AT_SOURCE = "withheld_at_source"
"""The two sides every capital-income figure falls on: still to declare on
the return, or already taxed by a withholding Depot (ticket 43) — never
mixed in one line, so nothing settled is declared a second time."""

ANLAGE_SO = "Anlage SO"
ANLAGE_KAP = "Anlage KAP"
ANLAGE_KAP_INV = "Anlage KAP-INV"

FUND_CATEGORIES = tuple(PARTIAL_EXEMPTION_STATUTES)
"""The fund types Anlage KAP-INV keeps apart — the Teilfreistellung
classifications (ticket 44), which the form lists in the same order."""


@dataclass(frozen=True)
class Field:
    """One field of a year's form: the line — or lines, where the form
    splits what the application cannot — and the label printed beside it."""

    lines: tuple[str, ...]
    label: str


def _private_sale_fields(
    *, krypto: tuple[str, str, str, str], andere: tuple[str, str, str, str], carried_to: str
) -> dict[str, Field]:
    """The two §23 blocks of an Anlage SO — the crypto block and "Andere
    Wirtschaftsgüter" — each given its four lines as that year's form
    numbers them: Veräußerungspreis, Anschaffungskosten, Werbungskosten,
    Gewinn / Verlust. The wording of these labels is the same on the 2024
    and 2025 forms except for the line the result is carried to."""
    basis_of = {
        "krypto": "Anschaffungskosten oder an deren Stelle tretender Wert (z. B. Teilwert,"
        " gemeiner Wert)",
        "andere": "Anschaffungskosten (ggf. gemindert um Absetzung für Abnutzung) oder an"
        " deren Stelle tretender Wert (z. B. Teilwert, gemeiner Wert)",
    }
    fields = {}
    for block, lines in (("krypto", krypto), ("andere", andere)):
        labels = (
            (
                "veraeusserungspreis",
                "Veräußerungspreis oder an dessen Stelle tretender Wert (z. B. gemeiner Wert)",
            ),
            ("anschaffungskosten", basis_of[block]),
            ("werbungskosten", "Werbungskosten im Zusammenhang mit dem Veräußerungsgeschäft"),
            ("gewinn", f"Gewinn / Verlust (zu übertragen nach Zeile {carried_to})"),
        )
        for line, (name, label) in zip(lines, labels, strict=True):
            fields[f"so.{block}.{name}"] = Field((line,), label)
    return fields


def _kap_fields(*, inlaendische: str, auslaendische: str) -> dict[str, Field]:
    """The Anlage KAP fields that sit on the same lines in 2024 and 2025 —
    each read from both years' forms, not assumed across. Only the printed
    exclusions on Zeilen 18 and 19 differ between the two."""
    return {
        "kap.abzug.kapitalertraege": Field(("7",), "Kapitalerträge"),
        # One figure, two lines: the form splits by the paying institution,
        # so the label is both lines' labels.
        "kap.kapitalertraege": Field(("18", "19"), f"{inlaendische} / {auslaendische}"),
        "kap.aktien_gewinne": Field(
            ("20",),
            "In den Zeilen 18 und 19 enthaltene Gewinne aus Aktienveräußerungen"
            " i. S. d. § 20 Abs. 2 Satz 1 Nr. 1 EStG",
        ),
        "kap.verluste_ohne_aktien": Field(
            ("22",),
            "In den Zeilen 18 und 19 enthaltene Verluste ohne Verluste aus der Veräußerung"
            " von Aktien",
        ),
        "kap.aktien_verluste": Field(
            ("23",),
            "In den Zeilen 18 und 19 enthaltene Verluste aus der Veräußerung von Aktien"
            " i. S. d. § 20 Abs. 2 Satz 1 Nr. 1 EStG",
        ),
        "kap.steuer.kapitalertragsteuer": Field(("37",), "Kapitalertragsteuer"),
        "kap.steuer.solidaritaetszuschlag": Field(("38",), "Solidaritätszuschlag"),
        "kap.steuer.kirchensteuer": Field(("39",), "Kirchensteuer zur Kapitalertragsteuer"),
        "kap.steuer.auslaendische_angerechnet": Field(("40",), "Angerechnete ausländische Steuern"),
        "kap.steuer.auslaendische_anrechenbar": Field(
            ("41",), "Anrechenbare noch nicht angerechnete ausländische Steuern"
        ),
    }


_KAP_TERMINGESCHAEFTE_FIELDS = {
    "kap.termingeschaefte_gewinne": Field(
        ("21",),
        "In den Zeilen 18 und 19 enthaltene Einkünfte aus Stillhalterprämien und Gewinne"
        " aus Termingeschäften",
    ),
    "kap.termingeschaefte_verluste": Field(("24",), "Verluste aus Termingeschäften"),
}
"""The lines the 2024 Anlage KAP still gives Termingeschäfte not taxed at
source. The 2025 form prints both as "frei": the JStG 2024 lifted the
offsetting restriction, and such results belong in the general lines."""

_KAP_INV_FIELDS = {
    "kapinv.ausschuettungen.aktienfonds": Field(
        ("4",), "Ausschüttungen aus: Aktienfonds i. S. d. § 2 Abs. 6 InvStG (vor Teilfreistellung)"
    ),
    "kapinv.ausschuettungen.mischfonds": Field(
        ("5",), "Ausschüttungen aus: Mischfonds i. S. d. § 2 Abs. 7 InvStG (vor Teilfreistellung)"
    ),
    "kapinv.ausschuettungen.immobilienfonds": Field(
        ("6",),
        "Ausschüttungen aus: Immobilienfonds i. S. d. § 2 Abs. 9 Satz 1 InvStG"
        " (vor Teilfreistellung und ohne Beträge laut Zeile 7)",
    ),
    "kapinv.ausschuettungen.auslands_immobilienfonds": Field(
        ("7",),
        "Ausschüttungen aus: Auslands-Immobilienfonds i. S. d. § 2 Abs. 9 Satz 2 InvStG"
        " (vor Teilfreistellung)",
    ),
    "kapinv.ausschuettungen.sonstige": Field(
        ("8",), "Ausschüttungen aus: sonstigen Investmentfonds"
    ),
    "kapinv.veraeusserung.aktienfonds": Field(
        ("14",),
        "Veräußerung von Investmentanteilen: Aktienfonds i. S. d. § 2 Abs. 6 InvStG"
        " (vor Teilfreistellung)",
    ),
    "kapinv.veraeusserung.mischfonds": Field(
        ("17",),
        "Veräußerung von Investmentanteilen: Mischfonds i. S. d. § 2 Abs. 7 InvStG"
        " (vor Teilfreistellung)",
    ),
    "kapinv.veraeusserung.immobilienfonds": Field(
        ("20",),
        "Veräußerung von Investmentanteilen: Immobilienfonds i. S. d. § 2 Abs. 9 Satz 1"
        " InvStG (vor Teilfreistellung und ohne Beträge laut Zeile 23)",
    ),
    "kapinv.veraeusserung.auslands_immobilienfonds": Field(
        ("23",),
        "Veräußerung von Investmentanteilen: Auslands-Immobilienfonds i. S. d. § 2 Abs. 9"
        " Satz 2 InvStG (vor Teilfreistellung)",
    ),
    "kapinv.veraeusserung.sonstige": Field(
        ("26",), "Veräußerung von Investmentanteilen: Sonstige Investmentfonds"
    ),
}
"""Anlage KAP-INV, whose lines and labels are the same on the 2024 and 2025
forms — each read from both. The form prints the fund type under a block
heading; the label here is the heading, shortened, then the printed line."""


LAYOUTS: dict[int, dict[str, Field]] = {
    2024: {
        # Anlage SO 2024 (2024AnlSO131NET to 133NET, September 2024).
        "so.leistungen.einnahmen_krypto": Field(
            ("11",),
            "Einnahmen im Zusammenhang mit Einheiten virtueller Währungen und / oder"
            " sonstigen Token:",
        ),
        **_private_sale_fields(
            krypto=("44", "45", "46", "47"), andere=("50", "51", "52", "53"), carried_to="54"
        ),
        "so.weitere_veraeusserungen": Field(
            ("55",),
            "Gewinne / Verluste aus weiteren Veräußerungen von Einheiten virtueller Währungen"
            " und sonstigen Token sowie anderen Wirtschaftsgütern (laut gesonderter"
            " Aufstellung)",
        ),
        # Anlage KAP 2024 (2024AnlKAP051NET to 053NET, September 2024) and
        # Anlage KAP-INV 2024 (September 2024).
        **_kap_fields(
            inlaendische="Inländische Kapitalerträge (ohne Beträge laut den Zeilen 24 bis 26a)",
            auslaendische="Ausländische Kapitalerträge (ohne Beträge laut den Zeilen 24, 25,"
            " 26a und 52)",
        ),
        **_KAP_TERMINGESCHAEFTE_FIELDS,
        **_KAP_INV_FIELDS,
    },
    2025: {
        # Anlage SO 2025 (2025AnlSO131NET to 133NET, September 2025).
        "so.leistungen.einnahmen_krypto": Field(
            ("15",), "Einnahmen im Zusammenhang mit Kryptowerten:"
        ),
        **_private_sale_fields(
            krypto=("48", "49", "50", "51"), andere=("54", "55", "56", "57"), carried_to="58"
        ),
        "so.weitere_veraeusserungen": Field(
            ("59",),
            "Gewinne / Verluste aus weiteren Veräußerungen von Kryptowerten sowie anderen"
            " Wirtschaftsgütern (laut gesonderter Aufstellung)",
        ),
        # Anlage KAP 2025 (2025AnlKAP051NET to 053NET, Oktober 2025) and
        # Anlage KAP-INV 2025 (September 2025).
        **_kap_fields(
            inlaendische="Inländische Kapitalerträge (ohne Beträge laut den Zeilen 26 und 26a)",
            auslaendische="Ausländische Kapitalerträge (ohne Beträge laut den Zeilen 26a und 52)",
        ),
        **_KAP_INV_FIELDS,
    },
}
"""Each mapped Tax Year's form fields, read from that year's official form in
the Formular-Management-System of the Bundesfinanzverwaltung — one year never
inferred from another (docs/research/tax-form-lines.md cites every form).
Adding a year means reading its forms and writing its table; a field shared
between years is shared only because both forms were read and agree."""


@dataclass(frozen=True)
class FormLine:
    """One figure where the form wants it. `form_lines` is the line it
    belongs on — several where the mapping is ambiguous, none where the year
    is unmapped — and `backed_by` names the records behind the amount in the
    appendix's own vocabulary ("leg:42"). `amount_eur` is None while the
    figure awaits a valuation, never a guess."""

    key: str
    form_lines: tuple[str, ...]
    label: str
    amount_eur: Decimal | None
    mapping: str
    side: str
    note: str | None
    backed_by: tuple[str, ...]


@dataclass(frozen=True)
class Balance:
    """A figure the section rests on that the form has no line for — a
    category's balance for the year, the amount a Freigrenze leaves taxable
    — shown so the lines beside it can be checked against it."""

    key: str
    label: str
    amount_eur: Decimal | None


@dataclass(frozen=True)
class TaxStatement:
    """Whether the section states a euro tax owed (ADR-0007): only where the
    rate is statutory. Where the personal marginal rate decides, `stated` is
    False, every amount is None, and the note says why."""

    stated: bool
    income_tax_eur: Decimal | None
    solidarity_surcharge_eur: Decimal | None
    church_tax_eur: Decimal | None
    total_eur: Decimal | None
    note: str


@dataclass(frozen=True)
class FormSection:
    """One block of one form, in the form's own order."""

    key: str
    form: str
    title: str
    lines: tuple[FormLine, ...]
    balances: tuple[Balance, ...]
    tax: TaxStatement
    # What the section as a whole must say — set where it states no lines
    # because the year awaits a valuation.
    note: str | None = None


@dataclass(frozen=True)
class TaxForms:
    """One Tax Year's figures in the shape of its forms. `line_numbers_year`
    is the year whose form the labels were read from — the report's own year
    where it is mapped, otherwise the nearest mapped year, lending its labels
    and no line number."""

    year: int
    line_numbers_mapped: bool
    line_numbers_year: int
    sections: tuple[FormSection, ...]


MARGINAL_RATE_NOTE = (
    "Taxed at the personal marginal rate, which this application does not know —"
    " the taxable amount is stated, never a euro tax owed."
)
"""Why the Anlage SO sections state no tax (ADR-0007)."""


@dataclass(frozen=True)
class _Sheet:
    """The year's form fields as a line is written from them."""

    year: int
    fields: dict[str, Field]
    fields_year: int

    @property
    def mapped(self) -> bool:
        return self.fields_year == self.year

    def line(
        self,
        key: str,
        amount_eur: Decimal | None,
        *,
        backed_by: tuple[str, ...],
        side: str = TO_DECLARE,
        note: str | None = None,
        also: tuple[str, ...] = (),
        ambiguous: bool = False,
    ) -> FormLine:
        """The figure on its field's line. `also` names further fields the
        figure may belong on instead — their lines join the field's own, and
        the mapping is ambiguous for it; `ambiguous` says the same of a
        figure whose one line does not ask for quite this amount."""
        field = self.fields[key]
        lines = field.lines + tuple(line for other in also for line in self.fields[other].lines)
        if not self.mapped:
            return FormLine(
                key=key,
                form_lines=(),
                label=field.label,
                amount_eur=amount_eur,
                mapping=UNMAPPED,
                side=side,
                note=_joined(
                    f"No line numbers are recorded for the {self.year} form — find this"
                    f" field by its label, given here as the {self.fields_year} form"
                    " printed it.",
                    note,
                ),
                backed_by=backed_by,
            )
        return FormLine(
            key=key,
            form_lines=lines,
            label=field.label,
            amount_eur=amount_eur,
            mapping=AMBIGUOUS if ambiguous or len(lines) > 1 else UNAMBIGUOUS,
            side=side,
            note=note,
            backed_by=backed_by,
        )


def _joined(*sentences: str | None) -> str | None:
    stated = [sentence for sentence in sentences if sentence]
    return " ".join(stated) if stated else None


def _sheet(year: int) -> _Sheet:
    # An unmapped year borrows the nearest mapped year's fields — the later
    # one on a tie — because a form resembles its neighbours, not the newest.
    fields_year = min(LAYOUTS, key=lambda mapped: (abs(mapped - year), -mapped))
    return _Sheet(year=year, fields=LAYOUTS[fields_year], fields_year=fields_year)


def year_forms(
    engine: Engine,
    *,
    year: int,
    section23: Section23Year,
    section22: Section22Year,
    section20: Section20Year,
) -> TaxForms:
    """The form sections of one Tax Year's computed figures, with the facts
    the layout turns on — what each Instrument is, which Depots withhold,
    which Account closed each futures position — read on one snapshot."""
    with lots.snapshot(engine) as connection:
        instrument_rows = lots_repository.instrument_rows(connection)
        withholding_accounts = capital_income_repository.withholding_accounts(connection)
        position_rows = futures_repository.closed_position_rows(connection)
    return build(
        year=year,
        section23=section23,
        section22=section22,
        section20=section20,
        instruments={row.id: row for row in instrument_rows},
        withholding_accounts=withholding_accounts,
        futures_accounts={row.id: row.account_id for row in position_rows},
    )


def build(
    *,
    year: int,
    section23: Section23Year,
    section22: Section22Year,
    section20: Section20Year,
    instruments: Mapping[int, Row],
    withholding_accounts: Set[int],
    futures_accounts: Mapping[int, int],
) -> TaxForms:
    """The year's figures laid out as its forms, pure. `instruments` maps an
    Instrument's id to its classification row (repositories/lots) — what a
    thing is decides which block of a form its figure belongs in;
    `withholding_accounts` are the Depots that tax at source, and
    `futures_accounts` maps a closed futures position to its Account."""
    sheet = _sheet(year)
    items = _capital_items(section20, instruments, withholding_accounts, futures_accounts)
    return TaxForms(
        year=year,
        line_numbers_mapped=sheet.mapped,
        line_numbers_year=sheet.fields_year,
        sections=(
            _leistungen(sheet, section22),
            _private_sales(sheet, section23, instruments),
            _capital_income(sheet, section20, items),
            _fund_income(sheet, section20, items),
        ),
    )


def _leistungen(sheet: _Sheet, section22: Section22Year) -> FormSection:
    """Anlage SO, Leistungen (§22 Nr. 3 EStG): every receipt this ledger
    pools there — staking, lending, mining, airdrops — is crypto-related, so
    the whole pool is the form's crypto Einnahmen. The form has no line for
    the Freigrenze; what it leaves taxable stands beside the line."""
    verdict = section22.freigrenze
    return FormSection(
        key="so.leistungen",
        form=ANLAGE_SO,
        title="Leistungen (§ 22 Nr. 3 EStG)",
        lines=(
            sheet.line(
                "so.leistungen.einnahmen_krypto",
                section22.total_income_eur,
                backed_by=tuple(f"leg:{income.leg_id}" for income in section22.incomes),
            ),
        ),
        balances=(
            Balance(
                key="so.leistungen.einkuenfte",
                label="Einkünfte aus Leistungen for the year",
                amount_eur=section22.total_income_eur,
            ),
            Balance(
                key="so.leistungen.taxable",
                label="Taxable after the Freigrenze (§ 22 Nr. 3 Satz 2 EStG)",
                amount_eur=verdict.taxable_income_eur if verdict is not None else None,
            ),
        ),
        tax=_NO_TAX_STATED,
    )


_PRIVATE_SALE_BLOCKS = (("crypto", "krypto"), ("cash", "andere"))
"""The Instrument families a private sale can be of (services/section23),
each with the Anlage SO block it is declared in: Kryptowerte, and "Andere
Wirtschaftsgüter" — where the Anleitung puts Fremdwährungen."""

_PRIVATE_SALE_FIGURES = (
    ("veraeusserungspreis", "proceeds_eur"),
    ("anschaffungskosten", "basis_eur"),
    ("werbungskosten", "costs_eur"),
    ("gewinn", "gain_eur"),
)


def _private_sales(
    sheet: _Sheet, section23: Section23Year, instruments: Mapping[int, Row]
) -> FormSection:
    """Anlage SO, private Veräußerungsgeschäfte (§23 EStG): one block per
    kind of asset, stating only the lot slices that count — an exempt or
    out-of-scope slice is not declared (section23.counts). A block takes a
    single disposal; with several the form wants the rest on its
    further-disposals line by separate schedule, so the block's figures —
    then the total of them all — say they are not one line's worth, and the
    appendix is that schedule. The form has no line for the Freigrenze."""
    lines = []
    for family, block in _PRIVATE_SALE_BLOCKS:
        counted = [
            (disposal, [piece for piece in disposal.consumptions if _counts(piece)])
            for disposal in section23.disposals
            if instruments[disposal.instrument_id].family == family
        ]
        counted = [(disposal, pieces) for disposal, pieces in counted if pieces]
        if not counted:
            continue
        several = len(counted) > 1
        backed_by = tuple(f"leg:{disposal.leg_id}" for disposal, _ in counted)
        for name, attribute in _PRIVATE_SALE_FIGURES:
            lines.append(
                sheet.line(
                    f"so.{block}.{name}",
                    _total(getattr(piece, attribute) for _, pieces in counted for piece in pieces),
                    backed_by=backed_by,
                    also=("so.weitere_veraeusserungen",) if several and name == "gewinn" else (),
                    ambiguous=several,
                    note=(
                        f"The total of {len(counted)} disposals. The block holds one; the form"
                        " wants the others on its further-disposals line, explained in a"
                        " separate schedule — the appendix lists each."
                    )
                    if several
                    else None,
                )
            )
    verdict = section23.freigrenze
    return FormSection(
        key="so.private_sales",
        form=ANLAGE_SO,
        title="Private Veräußerungsgeschäfte (§ 23 EStG)",
        lines=tuple(lines),
        balances=(
            Balance(
                key="so.private_sales.gesamtgewinn",
                label="Gesamtgewinn from private sales for the year",
                amount_eur=section23.total_gain_eur,
            ),
            Balance(
                key="so.private_sales.taxable",
                label="Taxable after the Freigrenze (§ 23 Abs. 3 Satz 5 EStG)",
                amount_eur=verdict.taxable_gain_eur if verdict is not None else None,
            ),
        ),
        tax=_NO_TAX_STATED,
    )


def _counts(piece: Consumption) -> bool:
    return counts(long_term=piece.long_term, basis_source=piece.basis_source)


def _total(amounts: Iterable[Decimal | None]) -> Decimal | None:
    """The sum, or None while any member awaits a valuation — a total
    cannot be stated around a missing member."""
    total = Decimal(0)
    for amount in amounts:
        if amount is None:
            return None
        total += amount
    return total


_NO_TAX_STATED = TaxStatement(
    stated=False,
    income_tax_eur=None,
    solidarity_surcharge_eur=None,
    church_tax_eur=None,
    total_eur=None,
    note=MARGINAL_RATE_NOTE,
)


_FUTURES_SOURCE = "futures_position:"


@dataclass(frozen=True)
class _CapitalItem:
    """One record of the year's capital income as the forms tell it apart:
    which pot it feeds, whether a fund produced it (and of which type),
    whether it is a disposal result or a receipt, and which side of the
    withholding line its Depot puts it on. `gross_eur` is before any
    Teilfreistellung — the figure the forms ask for — and None while it
    awaits a valuation."""

    source: str
    category: str
    fund_category: str | None
    disposal: bool
    settled: bool
    gross_eur: Decimal | None


def _capital_items(
    section20: Section20Year,
    instruments: Mapping[int, Row],
    withholding_accounts: Set[int],
    futures_accounts: Mapping[int, int],
) -> tuple[_CapitalItem, ...]:
    """The year's capital income, record by record: its receipts and
    securities disposals as their producers stated them, and its futures
    closes from the pot that counted them — the event shape names their
    position, and the position its Account."""
    items = [
        _CapitalItem(
            source=f"leg:{receipt.leg_id}",
            category=receipt.category,
            fund_category=_fund_category(instruments, receipt.paying_instrument_id),
            disposal=False,
            settled=receipt.settled_at_source,
            gross_eur=receipt.gross_eur,
        )
        for receipt in section20.receipts
    ]
    items.extend(
        _CapitalItem(
            source=f"leg:{disposal.leg_id}",
            category=disposal.category,
            fund_category=_fund_category(instruments, disposal.instrument_id),
            disposal=True,
            settled=disposal.account_id in withholding_accounts,
            gross_eur=disposal.gain_eur,
        )
        for disposal in section20.disposals
    )
    for balance in section20.balances or ():
        if balance.category != FUTURES_CATEGORY:
            continue
        for entry in balance.entries:
            source = entry.event.source
            if not source.startswith(_FUTURES_SOURCE):
                continue
            position_id = int(source.removeprefix(_FUTURES_SOURCE))
            items.append(
                _CapitalItem(
                    source=source,
                    category=FUTURES_CATEGORY,
                    fund_category=None,
                    disposal=True,
                    settled=futures_accounts.get(position_id) in withholding_accounts,
                    gross_eur=entry.event.gross_eur,
                )
            )
    return tuple(items)


def _fund_category(instruments: Mapping[int, Row], instrument_id: int | None) -> str | None:
    """The fund type of the Instrument that paid or was sold — None for
    everything that is not a fund."""
    if instrument_id is None:
        return None
    instrument = instruments[instrument_id]
    return instrument.fund_category if instrument.type in FUND_TYPES else None


_PAYING_INSTITUTION_NOTE = (
    "Zeile 18 takes income whose paying institution is domestic, Zeile 19 income paid"
    " through a foreign one. The ledger does not record where the paying institution"
    " sits, so the figure is stated once — enter it on the line that fits, or split it."
    " It is stated gross of any Quellensteuer."
)

_CERTIFICATE_NOTE = (
    "The form wants this as the broker's Steuerbescheinigung certifies it. This is the"
    " ledger's own figure, before any Teilfreistellung, for comparison with that"
    " certificate."
)

_FLAT_RATE_NOTE = (
    "The flat-rate tax on the year's whole taxable capital income — Anlage KAP and"
    " Anlage KAP-INV together — before crediting what was withheld at source."
)

_AWAITING_NOTE = "The year awaits a valuation, so no tax is stated."

_CREDITABLE_NOTE = (
    "The creditable part of what was withheld: each receipt's Quellensteuer up to its"
    " treaty limit. The appendix states what was withheld; any excess is reclaimable"
    " from the source country, not creditable here."
)

_KAP_TITLE = "Einkünfte aus Kapitalvermögen (§ 20 EStG)"
_KAP_INV_TITLE = "Investmenterträge, die nicht dem inländischen Steuerabzug unterlegen haben"


def _awaiting(section20: Section20Year) -> str:
    """Why a capital-income section states no line: the year awaits a
    valuation, and no figure is stated around a missing one
    (services/section20) — named in the events' own vocabulary."""
    return (
        "No line is stated: the year's capital income awaits a valuation of "
        f"{', '.join(section20.awaiting_valuation)}."
    )


def _capital_income(
    sheet: _Sheet, section20: Section20Year, items: tuple[_CapitalItem, ...]
) -> FormSection:
    """Anlage KAP (§20 EStG). What a withholding Depot already taxed stands
    on the withheld side with the tax taken from it; everything else is to
    declare — fund income excepted, which Anlage KAP-INV takes. The to-declare
    total is net of its losses, and the "enthaltene" lines restate what it
    contains: share gains, share losses, other losses — a loss as its amount.
    Where the year's form still gives Termingeschäfte lines of their own
    (2024), their losses stay out of the total, as that form's label says."""
    if section20.balances is None:
        return FormSection(
            key="kap",
            form=ANLAGE_KAP,
            title=_KAP_TITLE,
            lines=(),
            balances=(),
            tax=replace(_NO_TAX_STATED, note=_AWAITING_NOTE),
            note=_awaiting(section20),
        )
    declare = [item for item in items if not item.settled and item.fund_category is None]
    settled = [item for item in items if item.settled]
    apart = "kap.termingeschaefte_verluste" in sheet.fields

    def futures(item: _CapitalItem) -> bool:
        return item.category == FUTURES_CATEGORY

    def shares(item: _CapitalItem) -> bool:
        return item.category == SHARE_CATEGORY and item.disposal

    lines = []

    def state(
        key: str,
        members: list[_CapitalItem],
        *,
        negate: bool = False,
        side: str = TO_DECLARE,
        note: str | None = None,
        ambiguous: bool = False,
    ) -> None:
        if not members:
            return
        total = _total(item.gross_eur for item in members)
        lines.append(
            sheet.line(
                key,
                -total if negate and total is not None else total,
                backed_by=tuple(item.source for item in members),
                side=side,
                note=note,
                ambiguous=ambiguous,
            )
        )

    state(
        "kap.abzug.kapitalertraege",
        settled,
        side=WITHHELD_AT_SOURCE,
        note=_CERTIFICATE_NOTE,
        ambiguous=True,
    )
    state(
        "kap.kapitalertraege",
        [item for item in declare if not (apart and futures(item) and _loss(item))],
        note=_PAYING_INSTITUTION_NOTE,
    )
    state("kap.aktien_gewinne", [item for item in declare if shares(item) and _gain(item)])
    if apart:
        state(
            "kap.termingeschaefte_gewinne",
            [item for item in declare if futures(item) and _gain(item)],
        )
    state(
        "kap.verluste_ohne_aktien",
        [
            item
            for item in declare
            if _loss(item) and not shares(item) and not (apart and futures(item))
        ],
        negate=True,
    )
    state(
        "kap.aktien_verluste",
        [item for item in declare if shares(item) and _loss(item)],
        negate=True,
    )
    if apart:
        state(
            "kap.termingeschaefte_verluste",
            [item for item in declare if futures(item) and _loss(item)],
            negate=True,
        )
    lines.extend(_withheld_taxes(sheet, section20))

    assessment = section20.assessment
    balances = [
        Balance(
            key=f"kap.balance.{balance.category}",
            label=f"Balance of the {balance.category} category for the year",
            amount_eur=balance.balance_eur,
        )
        for balance in section20.balances or ()
    ]
    if assessment is not None:
        balances.extend(
            [
                Balance(
                    key="kap.combined",
                    label="Combined capital income after offsetting and carryforward",
                    amount_eur=assessment.combined_eur,
                ),
                Balance(
                    key="kap.allowance_applied",
                    label="Sparerpauschbetrag applied (§ 20 Abs. 9 EStG)",
                    amount_eur=assessment.allowance_applied_eur,
                ),
                Balance(
                    key="kap.taxable",
                    label="Taxable capital income",
                    amount_eur=assessment.taxable_eur,
                ),
            ]
        )
    return FormSection(
        key="kap",
        form=ANLAGE_KAP,
        title=_KAP_TITLE,
        lines=tuple(lines),
        balances=tuple(balances),
        tax=TaxStatement(
            stated=True,
            income_tax_eur=assessment.tax.income_tax_eur,
            solidarity_surcharge_eur=assessment.tax.solidarity_surcharge_eur,
            church_tax_eur=assessment.tax.church_tax_eur,
            total_eur=assessment.tax.total_eur,
            note=f"{_FLAT_RATE_NOTE} {assessment.personal_rate_note}",
        )
        if assessment is not None
        else replace(_NO_TAX_STATED, note=_AWAITING_NOTE),
        note=None,
    )


def _gain(item: _CapitalItem) -> bool:
    return item.gross_eur is not None and item.gross_eur > 0


def _loss(item: _CapitalItem) -> bool:
    return item.gross_eur is not None and item.gross_eur < 0


def _withheld_taxes(sheet: _Sheet, section20: Section20Year) -> list[FormLine]:
    """The tax already taken out of the year's receipts: the German
    components as withheld, and the creditable Quellensteuer — each
    receipt's own, by the engine's one rule (section20.creditable_eur) — on
    the line for tax a withholding Depot already credited or the line for
    tax still to credit, by the Depot that received it. Every figure is
    stated by the time this runs: a year awaiting a valuation states no
    capital-income line at all."""
    statement = section20.withholding
    if statement is None:
        return []
    lines = []
    taxed = tuple(
        f"leg:{receipt.leg_id}"
        for receipt in section20.receipts
        if receipt.kapitalertragsteuer_eur
        or receipt.solidarity_surcharge_eur
        or receipt.church_tax_eur
    )
    if taxed:
        for key, amount in (
            ("kap.steuer.kapitalertragsteuer", statement.german.kapitalertragsteuer_eur),
            ("kap.steuer.solidaritaetszuschlag", statement.german.solidarity_surcharge_eur),
            ("kap.steuer.kirchensteuer", statement.german.church_tax_eur),
        ):
            lines.append(sheet.line(key, amount, backed_by=taxed, side=WITHHELD_AT_SOURCE))
    rates = {credit.country: credit.treaty_rate for credit in statement.foreign}
    for key, settled, side in (
        ("kap.steuer.auslaendische_angerechnet", True, WITHHELD_AT_SOURCE),
        ("kap.steuer.auslaendische_anrechenbar", False, TO_DECLARE),
    ):
        foreign = [
            receipt
            for receipt in section20.receipts
            if receipt.source_country is not None and receipt.settled_at_source is settled
        ]
        if foreign:
            lines.append(
                sheet.line(
                    key,
                    sum(
                        (
                            creditable_eur(
                                gross_eur=receipt.gross_eur,
                                withheld_eur=receipt.foreign_withholding_eur,
                                treaty_rate=rates[receipt.source_country],
                            )
                            for receipt in foreign
                        ),
                        Decimal(0),
                    ),
                    backed_by=tuple(f"leg:{receipt.leg_id}" for receipt in foreign),
                    side=side,
                    note=_CREDITABLE_NOTE,
                )
            )
    return lines


def _fund_income(
    sheet: _Sheet, section20: Section20Year, items: tuple[_CapitalItem, ...]
) -> FormSection:
    """Anlage KAP-INV: fund income no German Depot taxed, per fund type and
    in full — before Teilfreistellung, which the Finanzamt applies (the
    form's own instruction). A disposal result is one signed Gewinn /
    Verlust figure per fund type."""
    declare = [item for item in items if not item.settled and item.fund_category is not None]
    lines = []
    awaiting = section20.balances is None
    for block, disposal in (("ausschuettungen", False), ("veraeusserung", True)):
        for category in FUND_CATEGORIES:
            members = [
                item
                for item in declare
                if item.fund_category == category and item.disposal is disposal
            ]
            if members and not awaiting:
                lines.append(
                    sheet.line(
                        f"kapinv.{block}.{category}",
                        _total(item.gross_eur for item in members),
                        backed_by=tuple(item.source for item in members),
                    )
                )
    return FormSection(
        key="kapinv",
        form=ANLAGE_KAP_INV,
        title=_KAP_INV_TITLE,
        lines=tuple(lines),
        balances=(),
        tax=replace(
            _NO_TAX_STATED,
            note="Taxed within the capital-income assessment stated under Anlage KAP.",
        ),
        note=_awaiting(section20) if awaiting else None,
    )
