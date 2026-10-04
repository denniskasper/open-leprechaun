"""The eToro statement connector against recorded fixtures (ticket 50,
ADR-0008): a broker with no API, served by the account statement it exports.

The statement is a workbook, and the Account Activity sheet is its ledger:
what moved the balance, row by row. It names a position by a ticker alone —
the ISIN stands only on the sheets of closed positions and of dividends — so
the connector joins the sheets by Position ID and states a security by its
ISIN wherever the statement does. What is no security — a leveraged or short
position, a coin — is passed over by name, never landed and never dropped.

The fixture is the statement's own shape with invented values; these tests
build a real .xlsx from it, so the workbook reader is under test with it.
"""

import base64
import io
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from open_leprechaun.ports.csv_connector import FileRejectedError, ParsedFile
from open_leprechaun.ports.etoro import EtoroStatementConnector

FIXTURE = Path(__file__).parent / "fixtures" / "etoro" / "recorded.json"

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"


def recorded() -> dict[str, list[list]]:
    """The fixture's sheets, numbers kept as the digits they were written
    with."""
    sheets = json.loads(FIXTURE.read_text(), parse_float=Decimal, parse_int=Decimal)
    sheets.pop("_provenance")
    return sheets


def _column(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def workbook_bytes(sheets: dict[str, list[list]], *, inline_strings: bool = False) -> bytes:
    """A minimal .xlsx of these sheets: text as shared strings (or inline),
    numbers as numeric cells, None as no cell at all."""
    strings: list[str] = []

    def cell(reference: str, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            if inline_strings:
                return f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            if value not in strings:
                strings.append(value)
            return f'<c r="{reference}" t="s"><v>{strings.index(value)}</v></c>'
        return f'<c r="{reference}"><v>{value}</v></c>'

    parts: dict[str, str] = {}
    for number, rows in enumerate(sheets.values(), start=1):
        body = "".join(
            f'<row r="{r}">'
            + "".join(cell(f"{_column(c)}{r}", value) for c, value in enumerate(row))
            + "</row>"
            for r, row in enumerate(rows, start=1)
        )
        parts[f"xl/worksheets/sheet{number}.xml"] = (
            f'<worksheet xmlns="{_MAIN}"><sheetData>{body}</sheetData></worksheet>'
        )
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{_MAIN}" xmlns:r="{_RELATIONSHIPS}"><sheets>'
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{number}" r:id="rId{number}"/>'
            for number, name in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{_PACKAGE}">'
        + "".join(
            f'<Relationship Id="rId{number}" Type="{_RELATIONSHIPS}/worksheet"'
            f' Target="worksheets/sheet{number}.xml"/>'
            for number in range(1, len(sheets) + 1)
        )
        + "</Relationships>"
    )
    parts["xl/sharedStrings.xml"] = (
        f'<sst xmlns="{_MAIN}">'
        + "".join(f"<si><t>{escape(string)}</t></si>" for string in strings)
        + "</sst>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8"?>' + content)
    return buffer.getvalue()


def content_of(sheets: dict[str, list[list]], **options) -> str:
    """The workbook as the import request carries it: its bytes in base64."""
    return base64.b64encode(workbook_bytes(sheets, **options)).decode()


def parse(sheets: dict[str, list[list]] | None = None, **options) -> ParsedFile:
    return EtoroStatementConnector().parse(content_of(sheets or recorded(), **options))


ACTIVITY_HEADER = recorded()["Account Activity"][0]


def activity(*rows: list) -> dict[str, list[list]]:
    """A statement of these Account Activity rows alone — the two lookup
    sheets empty."""
    sheets = recorded()
    sheets["Account Activity"] = [ACTIVITY_HEADER, *rows]
    sheets["Closed Positions"] = sheets["Closed Positions"][:1]
    sheets["Dividends"] = sheets["Dividends"][:1]
    return sheets


def at(day: int, month: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2031, month, day, hour, minute, second, tzinfo=UTC)


# --- What the connector declares ---


def test_the_connector_declares_the_statement_its_timezone_and_its_units():
    """A statement in local time or in cents would land in the wrong tax
    year or a hundred times over, so both are stated before a file is read."""
    connector = EtoroStatementConnector()

    assert connector.connector == "etoro"
    assert connector.name == "eToro"
    assert connector.file_format == "xlsx"
    # The statement prints its timestamps on the UTC clock.
    assert connector.timezone == "UTC"
    assert "XLSX" in connector.expects
    # Whole dollars and whole units of a security, fractions included.
    assert "US dollars" in connector.expects


# --- Buys and sells ---


def test_a_purchase_names_its_security_by_the_isin_another_sheet_states():
    """The activity names only "AAPL/USD"; the closed position of the same
    Position ID carries the ISIN, which is the security's identity."""
    statement = parse().statement

    bought = next(trade for trade in statement.trades if trade.external_id == "2000000001:open")
    assert bought.side == "buy"
    assert bought.occurred_at == at(3, 1, 14, 30)
    assert bought.security.isin == "US0378331005"
    assert bought.security.symbol == "AAPL"
    assert bought.security.name == "Apple"
    assert bought.quantity == Decimal("10")
    assert bought.settled_amount == Decimal("1800")
    assert bought.settlement_currency == "USD"
    assert bought.original is None


def test_a_sale_settles_for_the_whole_amount_returned_its_commission_stated_apart():
    """A closing row's Amount is everything returned — the stake and the
    result — and the commission is its own row, a cost of the security."""
    statement = parse().statement

    (sold,) = (trade for trade in statement.trades if trade.side == "sell")
    assert sold.external_id == "2000000001:close:2031-03-10T15:00:00"
    assert sold.occurred_at == at(10, 3, 15)
    assert sold.quantity == Decimal("10")
    assert sold.settled_amount == Decimal("2000")
    (commission,) = sold.fees
    assert commission.name == "Commission"
    assert commission.amount == Decimal("1")
    assert commission.currency == "USD"
    assert commission.charged_against == "security"


def test_a_stamp_duty_is_a_fee_of_the_purchase_it_was_charged_on():
    """An ISIN known only from a dividend names the purchase all the same,
    and fractional units stay fractional."""
    statement = parse().statement

    bought = next(trade for trade in statement.trades if trade.external_id == "2000000002:open")
    assert bought.security.isin == "IE00B3XXRP09"
    assert bought.security.symbol == "VUSA.L"
    assert bought.security.name == "Vanguard S&P 500 UCITS ETF"
    assert bought.quantity == Decimal("10.5")
    assert [(fee.name, fee.amount, fee.charged_against) for fee in bought.fees] == [
        ("SDRT", Decimal("4.5"), "security")
    ]


def test_a_position_still_open_states_no_isin_and_names_its_ticker_alone():
    """Nothing in the statement gives a position its ISIN until it closes or
    pays a dividend. The ticker is then all there is — a resolution hint for
    the ledger to answer, never an identity made up here."""
    statement = parse().statement

    bought = next(trade for trade in statement.trades if trade.external_id == "2000000005:open")
    assert bought.security.isin is None
    assert bought.security.symbol == "NVDA"
    assert bought.security.name == "NVDA"


def test_a_ticker_is_named_by_the_isin_of_another_position_in_the_same_paper():
    """Two positions in one ticker are one security: the ISIN the closed one
    states names the open one too."""
    sheets = recorded()
    sheets["Account Activity"].append(
        [
            "11/03/2031 09:00:00",
            "Open Position",
            "AAPL/USD",
            950,
            5,
            0,
            0,
            0,
            "2000000009",
            "Stocks",
            0,
        ]
    )

    statement = parse(sheets).statement

    again = next(trade for trade in statement.trades if trade.external_id == "2000000009:open")
    assert again.security.isin == "US0378331005"


def test_partial_closes_of_one_position_are_each_their_own_sale():
    rows = [
        ["03/01/2031 14:30:00", "Open Position", "AAPL/USD", 1800, 10, 0, 0, 0, "7", "Stocks", 0],
        ["04/02/2031 10:00:00", "Position closed", "AAPL/USD", 800, 4, 80, 0, 0, "7", "Stocks", 0],
        ["04/02/2031 10:00:01", "Commission", "On Close", -1, "-", -1, 0, 0, "7", "Stocks", 0],
        [
            "05/03/2031 10:00:00",
            "Position closed",
            "AAPL/USD",
            1300,
            6,
            220,
            0,
            0,
            "7",
            "Stocks",
            0,
        ],
        ["05/03/2031 10:00:01", "Commission", "On Close", -2, "-", -2, 0, 0, "7", "Stocks", 0],
    ]

    statement = parse(activity(*rows)).statement

    sales = [trade for trade in statement.trades if trade.side == "sell"]
    assert [sale.external_id for sale in sales] == [
        "7:close:2031-02-04T10:00:00",
        "7:close:2031-03-05T10:00:00",
    ]
    assert [sale.quantity for sale in sales] == [Decimal("4"), Decimal("6")]
    assert [[fee.amount for fee in sale.fees] for sale in sales] == [[Decimal("1")], [Decimal("2")]]


def test_a_sale_whose_purchase_predates_the_statement_lands_with_a_word():
    rows = [
        ["04/02/2031 10:00:00", "Position closed", "AAPL/USD", 800, 4, 80, 0, 0, "7", "Stocks", 0],
    ]

    parsed = parse(activity(*rows))

    (sold,) = parsed.statement.trades
    assert sold.side == "sell"
    assert any(
        "1 sale closes a position this statement shows no purchase of" in warning
        for warning in parsed.warnings
    )


def test_a_fee_listed_before_its_trade_still_attaches_to_it():
    """Rows of one second may come in either order; a fee names its trade
    by position, not by where it stands."""
    rows = [
        ["03/01/2031 14:30:00", "SDRT", "-", -4.5, "-", 0, 0, 0, "7", "Stocks", 0],
        ["03/01/2031 14:30:00", "Open Position", "AAPL/USD", 1800, 10, 0, 0, 0, "7", "Stocks", 0],
        ["04/02/2031 10:00:00", "Commission", "On Close", -1, "-", 0, 0, 0, "7", "Stocks", 0],
        ["04/02/2031 10:00:01", "Position closed", "AAPL/USD", 800, 10, 0, 0, 0, "7", "Stocks", 0],
    ]

    parsed = parse(activity(*rows))

    bought, sold = parsed.statement.trades
    assert [fee.name for fee in bought.fees] == ["SDRT"]
    assert [fee.name for fee in sold.fees] == ["Commission"]
    assert parsed.statement.passed_over == ()


def test_an_opening_that_states_its_leverage_is_no_security_even_while_open():
    """A position still open has no closed-position row to state its
    leverage; where the opening itself does, that decides — so a later
    statement cannot disagree about what the position was."""
    rows = [
        ["03/01/2031 14:30:00", "Open Position", "AAPL/USD x2", 900, 10, 0, 0, 0, "7", "Stocks", 0]
    ]

    parsed = parse(activity(*rows))

    assert parsed.statement.trades == ()
    assert descriptions(parsed)[0].startswith("Position 7 in AAPL/USD x2 — a leveraged or short")


def test_a_close_that_returned_nothing_is_named_and_the_rest_still_lands():
    rows = [
        ["03/01/2031 14:30:00", "Open Position", "AAPL/USD", 1800, 10, 0, 0, 0, "7", "Stocks", 0],
        [
            "04/02/2031 10:00:00",
            "Position closed",
            "AAPL/USD",
            0,
            10,
            -1800,
            0,
            0,
            "7",
            "Stocks",
            0,
        ],
    ]

    parsed = parse(activity(*rows))

    assert [trade.side for trade in parsed.statement.trades] == ["buy"]
    assert "Position closed on position 7 in AAPL/USD was left out" in descriptions(parsed)[0]


def test_a_cash_row_signed_against_its_type_is_named_never_flipped():
    """A deposit that takes money out is not a deposit the connector
    understands; turning it into one would invent cash."""
    rows = [
        ["02/01/2031 09:00:00", "Deposit", "-", -100, "-", 0, 0, 0, "-", "-", 0],
        ["02/01/2031 09:00:01", "Withdraw Fee", "-", 5, "-", 0, 0, 0, "-", "-", 0],
    ]

    parsed = parse(activity(*rows))

    assert parsed.statement.cash_movements == () and parsed.statement.account_fees == ()
    assert descriptions(parsed) == [
        "Deposit of -100 USD was left out — the statement does not say what it is.",
        "Withdraw Fee of 5 USD was left out — the statement does not say what it is.",
    ]


# --- Dividends and what was withheld ---


def test_a_dividend_is_the_net_with_the_withholding_and_its_source_country():
    """The Dividends sheet states the tax withheld beside the net; the
    country that withheld is the one the paying security's ISIN names."""
    statement = parse().statement

    paid = next(row for row in statement.dividends if row.external_id.startswith("2000000001"))
    assert paid.external_id == "2000000001:dividend:2031-02-15"
    assert paid.kind == "dividend"
    # The instant is the activity's, not the sheet's bare date.
    assert paid.occurred_at == at(15, 2, 13, 0, 5)
    assert paid.amount == Decimal("2.04")
    assert paid.currency == "USD"
    assert paid.security.isin == "US0378331005"
    assert paid.foreign_withholding == Decimal("0.36")
    assert paid.source_country == "US"
    assert paid.gross_amount == Decimal("2.4")
    assert paid.gross_currency == "USD"


def test_a_dividend_booked_the_day_after_the_sheet_dates_it_keeps_its_withholding():
    sheets = recorded()
    booked = next(row for row in sheets["Account Activity"] if row[1] == "Dividend")
    booked[0] = "16/02/2031 00:10:00"

    statement = parse(sheets).statement

    paid = next(row for row in statement.dividends if row.external_id.startswith("2000000001"))
    assert paid.external_id == "2000000001:dividend:2031-02-16"
    assert paid.foreign_withholding == Decimal("0.36")


def test_a_dividend_nothing_was_withheld_from_declares_no_withholding():
    statement = parse().statement

    paid = next(row for row in statement.dividends if row.external_id.startswith("2000000002"))
    assert paid.amount == Decimal("3.1")
    assert paid.security.isin == "IE00B3XXRP09"
    assert paid.foreign_withholding is None
    assert paid.source_country is None


def test_no_german_tax_is_declared_because_the_statement_reports_none():
    """The statement has no column for Kapitalertragsteuer, its surcharge or
    church tax — so none is stated, rather than a zero that would read as
    "nothing was withheld"."""
    statement = parse().statement

    assert all(
        row.kapitalertragsteuer is None
        and row.solidarity_surcharge is None
        and row.church_tax is None
        for row in statement.dividends
    )


def test_the_inferred_source_country_is_said_out_loud():
    parsed = parse()

    assert any("country of the paying security's ISIN" in warning for warning in parsed.warnings)


def test_a_dividend_the_dividends_sheet_does_not_list_lands_net_alone():
    rows = [
        ["03/01/2031 14:30:00", "Open Position", "AAPL/USD", 1800, 10, 0, 0, 0, "7", "Stocks", 0],
        ["15/02/2031 13:00:05", "Dividend", "AAPL/USD", 2.04, "-", 2.04, 0, 0, "7", "Stocks", 0],
    ]

    statement = parse(activity(*rows)).statement

    (paid,) = statement.dividends
    assert paid.amount == Decimal("2.04")
    assert paid.security.symbol == "AAPL"
    assert paid.foreign_withholding is None and paid.gross_amount is None


def test_interest_on_uninvested_cash_names_no_security():
    statement = parse().statement

    (interest,) = (row for row in statement.dividends if row.kind == "interest")
    assert interest.external_id == "interest-payment:2031-03-20T08:00:00:0.75"
    assert interest.amount == Decimal("0.75")
    assert interest.security is None


# --- Cash movements and fees ---


def test_deposits_and_withdrawals_are_cash_movements_in_dollars():
    statement = parse().statement

    assert [
        (row.external_id, row.direction, row.amount, row.currency, row.occurred_at)
        for row in statement.cash_movements
    ] == [
        ("deposit:2031-01-02T09:00:00:5000", "in", Decimal("5000"), "USD", at(2, 1, 9)),
        ("withdraw-request:2031-03-25T10:00:00:-300", "out", Decimal("300"), "USD", at(25, 3, 10)),
    ]


def test_a_withdrawal_fee_is_a_cost_of_the_depot_itself():
    statement = parse().statement

    (fee,) = statement.account_fees
    assert fee.external_id == "withdraw-fee:2031-03-25T10:00:00:-5"
    assert fee.amount == Decimal("5")
    assert fee.currency == "USD"


def test_identical_rows_keep_distinct_identifiers():
    """Two deposits of one amount in one second are two facts; the same two
    rows in an overlapping statement are the same two identifiers."""
    row = ["02/01/2031 09:00:00", "Deposit", "-", 100, "-", 100, 0, 0, "-", "-", 0]

    statement = parse(activity(row, row)).statement

    assert [movement.external_id for movement in statement.cash_movements] == [
        "deposit:2031-01-02T09:00:00:100",
        "deposit:2031-01-02T09:00:00:100:2",
    ]


# --- Passed over by name ---


def descriptions(parsed: ParsedFile) -> list[str]:
    return [passed.description for passed in parsed.statement.passed_over]


def test_a_leveraged_position_is_passed_over_whole_with_every_row_it_moved():
    """A contract for difference is no security: its opening, its overnight
    fee and its close are named once, together, and none of them lands."""
    parsed = parse()

    assert (
        "Position 2000000003 in EURUSD — a leveraged or short position is a contract for"
        " difference, not a security — was left out with the 3 rows that moved its cash"
        " (net 18.5 USD)."
    ) in descriptions(parsed)
    assert all("2000000003" not in trade.external_id for trade in parsed.statement.trades)


def test_a_coin_is_passed_over_because_a_statement_cannot_name_it():
    parsed = parse()

    assert (
        "Position 2000000004 in BTC/USD — a coin, which the statement names by a ticker"
        " alone — was left out with the 1 row that moved its cash (net -400 USD)."
    ) in descriptions(parsed)


def test_a_position_marked_stock_but_leveraged_is_still_no_security():
    """The closed position's leverage and direction decide, whatever the
    asset type says."""
    sheets = recorded()
    leverage = sheets["Closed Positions"][0].index("Leverage")
    sheets["Closed Positions"][1][leverage] = 2

    parsed = parse(sheets)

    assert all("2000000001" not in trade.external_id for trade in parsed.statement.trades)
    assert any(text.startswith("Position 2000000001 in AAPL/USD") for text in descriptions(parsed))


def test_a_split_is_named_for_the_admin_to_record():
    parsed = parse()

    (split,) = (passed for passed in parsed.statement.passed_over if "Split" in passed.description)
    assert split.occurred_at == at(2, 4, 7, 30)
    assert split.description == (
        "corp action: Split NVDA/USD 10:1 — record it as a Corporate Action; the units of"
        " earlier rows are as they were before it."
    )


def test_a_type_the_connector_does_not_know_is_named_never_guessed():
    parsed = parse()

    assert "Adjustment of 1.23 USD was left out — the statement does not say what it is." in (
        descriptions(parsed)
    )
    assert (
        "Loyalty cashback of 2 USD was left out — the statement does not say what it is."
        in descriptions(parsed)
    )


def test_rows_that_move_nothing_are_counted_not_silently_dropped():
    parsed = parse()

    assert "1 row that moves nothing was left out: Edit Stop Loss." in parsed.warnings


def test_cash_the_ledger_will_not_see_is_said_once():
    parsed = parse()

    assert any("the Depot's cash will differ from the statement's" in w for w in parsed.warnings)


# --- The period covered ---


def test_the_period_is_the_one_the_account_summary_states():
    covered = parse().statement.covered

    assert covered.start == at(1, 1)
    assert covered.end == datetime(2031, 12, 31, 23, 59, 59, tzinfo=UTC)


def test_without_a_stated_period_the_activity_itself_bounds_it():
    sheets = recorded()
    del sheets["Account Summary"]

    covered = parse(sheets).statement.covered

    assert covered.start == at(2, 1, 9)
    assert covered.end == at(6, 4, 10)


# --- How cells are stored ---


def test_a_timestamp_stored_as_a_date_serial_reads_as_the_same_instant():
    """A workbook keeps a date as days since 30 December 1899, the time of
    day as the fraction."""
    days = (date(2031, 1, 3) - date(1899, 12, 30)).days
    serial = Decimal(days) + Decimal(14 * 3600 + 30 * 60) / Decimal(86400)
    rows = [[serial, "Open Position", "AAPL/USD", 1800, 10, 0, 0, 0, "7", "Stocks", 0]]

    (bought,) = parse(activity(*rows)).statement.trades

    assert bought.occurred_at == at(3, 1, 14, 30)


def test_numbers_stored_as_text_and_inline_strings_read_the_same():
    rows = [
        [
            "03/01/2031 14:30:00",
            "Open Position",
            "AAPL/USD",
            "1800.50",
            "10",
            "0",
            "0",
            "0",
            7,
            "Stocks",
            "0",
        ]
    ]

    (bought,) = parse(activity(*rows), inline_strings=True).statement.trades

    assert bought.external_id == "7:open"
    assert bought.settled_amount == Decimal("1800.5")
    assert bought.quantity == Decimal("10")


def test_binary_noise_in_a_stored_number_is_rounded_away():
    """A workbook stores doubles: 0.1 + 0.2 arrives as 0.30000000000000004."""
    rows = [
        [
            "03/01/2031 14:30:00",
            "Open Position",
            "AAPL/USD",
            Decimal("0.30000000000000004"),
            10,
            0,
            0,
            0,
            "7",
            "Stocks",
            0,
        ]
    ]

    (bought,) = parse(activity(*rows)).statement.trades

    assert bought.settled_amount == Decimal("0.3")


# --- Refusals ---


def refusal_of(content: str) -> str:
    with pytest.raises(FileRejectedError) as refused:
        EtoroStatementConnector().parse(content)
    return str(refused.value)


def test_a_file_that_is_no_workbook_is_refused():
    assert "not an eToro account statement" in refusal_of("Date,Type\n1,2\n")
    assert "not an eToro account statement" in refusal_of(base64.b64encode(b"PK nothing").decode())


def test_a_workbook_counting_its_dates_from_1904_is_refused():
    """Its serials would read four years off."""
    data = workbook_bytes(recorded())
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(patched, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "xl/workbook.xml":
                content = content.replace(b"<sheets>", b'<workbookPr date1904="1"/><sheets>')
            target.writestr(name, content)

    assert "not an eToro account statement" in refusal_of(
        base64.b64encode(patched.getvalue()).decode()
    )


def test_a_workbook_without_the_account_activity_is_refused():
    sheets = recorded()
    del sheets["Account Activity"]

    assert "no 'Account Activity' sheet" in refusal_of(content_of(sheets))


def test_a_statement_in_another_language_is_refused_with_what_to_do():
    sheets = {"Kontoaktivität": [["Datum", "Typ"]], "Geschlossene Positionen": [["Positions-ID"]]}

    assert "account language set to English" in refusal_of(content_of(sheets))


def test_an_older_layout_without_the_columns_it_needs_is_refused():
    sheets = recorded()
    sheets["Account Activity"] = [row[:4] + row[5:] for row in sheets["Account Activity"]]

    assert "'Units / Contracts'" in refusal_of(content_of(sheets))


def test_the_older_units_header_is_the_same_column():
    sheets = recorded()
    header = sheets["Account Activity"][0]
    header[header.index("Units / Contracts")] = "Units"

    assert len(parse(sheets).statement.trades) == 4


def test_a_statement_in_another_account_currency_is_refused():
    sheets = recorded()
    sheets["Account Summary"][3] = ["Currency", "GBP"]

    assert "states its amounts in GBP" in refusal_of(content_of(sheets))


def test_a_timestamp_the_connector_cannot_read_is_refused_naming_the_row():
    rows = [["2031-01-03 14:30", "Deposit", "-", 100, "-", 100, 0, 0, "-", "-", 0]]

    assert "Row 2" in refusal_of(content_of(activity(*rows)))


def test_an_amount_the_connector_cannot_read_is_refused_naming_the_row():
    rows = [["03/01/2031 14:30:00", "Deposit", "-", "1.234,56", "-", 100, 0, 0, "-", "-", 0]]

    assert "Row 2" in refusal_of(content_of(activity(*rows)))
