"""The column-mapping port (ticket 33): an unsupported venue does not block
the Admin. A ColumnMapping is the Admin's own declaration of one file shape —
which column carries which ledger field, the exact datetime format and
timezone, the decimal convention — and the port interprets a file under it:
leniently for the mapping screen's live preview, strictly as a CSV Connector
for the import flow.

Nothing is guessed: an ambiguous date needs its declared format and timezone,
an undeclared type value is a stated problem, and the strict parse refuses a
file the mapping cannot read completely rather than mis-parsing it.
"""

from datetime import UTC, datetime
from decimal import Decimal

from open_leprechaun.ports.column_mapping import (
    MAPPED_TYPES,
    ColumnMapping,
    MappingConnector,
    defects,
    interpret,
)
from open_leprechaun.ports.csv_connector import FileRejectedError
from open_leprechaun.services.transactions import TRANSACTION_TYPES

BROKER_EXPORT = (
    "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n"
    "01.07.2026 14:30;Einzahlung;BTC;0,5;0,0001;abc-1\n"
    "02.01.2026 09:00;Auszahlung;BTC;-0,2;;abc-2\n"
)


def mapping(**overrides) -> ColumnMapping:
    given = dict(
        occurred_at="Datum",
        datetime_format="%d.%m.%Y %H:%M",
        timezone="Europe/Berlin",
        delimiter=";",
        decimal_comma=True,
        quantity="Betrag",
        symbol="Coin",
        type="Typ",
        type_values={"Einzahlung": "transfer_in", "Auszahlung": "transfer_out"},
        external_id="Referenz",
        fee_quantity="Gebühr",
    )
    given.update(overrides)
    return ColumnMapping(**given)


def test_an_empty_mapping_names_everything_a_declaration_still_lacks():
    """Required fields are enforced in sentences, not silence: the timestamp
    and quantity columns, the format and timezone, and a symbol and type each
    from a column or fixed — nothing defaults, nothing is guessed."""
    answered = interpret(BROKER_EXPORT, ColumnMapping(delimiter=";"))

    assert answered.defects == (
        "No column is assigned to the timestamp.",
        "The datetime format is not declared — an ambiguous date is never guessed.",
        "The timezone is not declared — a bare timestamp is never guessed.",
        "No column is assigned to the quantity.",
        "The symbol comes from a column or is fixed for the whole file; assign one.",
        "The type comes from a column or is fixed for the whole file; assign one.",
    )
    # The columns still answer — the mapping screen builds its pickers from
    # them before anything is assigned.
    assert answered.columns == ("Datum", "Typ", "Coin", "Betrag", "Gebühr", "Referenz")


def test_a_format_carrying_its_own_offset_declares_no_timezone_besides():
    offset_format = mapping(datetime_format="%d.%m.%Y %H:%M %z")
    assert (
        "The format reads a UTC offset from each timestamp, so a timezone is not declared besides."
        in defects(offset_format)
    )
    assert defects(mapping(datetime_format="%d.%m.%Y %H:%M %z", timezone=None)) == ()


def test_a_timezone_nothing_answers_to_is_a_defect():
    assert defects(mapping(timezone="Mitteleuropa")) == (
        "'Mitteleuropa' is not an IANA timezone name.",
    )


def test_a_type_target_outside_the_vocabulary_is_a_defect():
    assert defects(mapping(type_values={"Einzahlung": "deposit"})) == (
        "'deposit' is not an importable transaction type.",
    )


def test_the_mapped_vocabulary_is_the_single_role_types_without_opening_balance():
    """The port keeps its own literal so it depends on no service; this pins
    it to the ledger's vocabulary — one file row states one movement, and an
    opening balance is the Admin's declaration, never an import's."""
    single_role = [
        name
        for name, rules in TRANSACTION_TYPES.items()
        if len(rules.requires) == 1 and name != "opening_balance"
    ]
    assert list(MAPPED_TYPES) == single_role


def test_a_complete_mapping_interprets_the_first_rows_normalized():
    """The live preview's answer: every column the file carries, and each row
    read under the mapping — timestamps converted from the declared timezone
    to UTC (summer and winter offsets differ, so both rows prove DST),
    amounts read under the declared decimal convention, direction taken from
    the type rather than the sign."""
    answered = interpret(BROKER_EXPORT, mapping())

    assert answered.columns == ("Datum", "Typ", "Coin", "Betrag", "Gebühr", "Referenz")
    assert answered.defects == ()
    assert answered.row_count == 2
    first, second = answered.rows
    assert first.number == 1
    assert first.occurred_at == datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    assert first.type == "transfer_in"
    assert first.symbol == "BTC"
    assert first.quantity == Decimal("0.5")
    assert first.fee_quantity == Decimal("0.0001")
    assert first.external_id == "abc-1"
    assert first.problems == ()
    assert second.occurred_at == datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    assert second.type == "transfer_out"
    assert second.quantity == Decimal("0.2")
    assert second.fee_quantity is None
    assert second.problems == ()


def test_an_unmapped_type_value_and_a_bad_cell_are_problems_on_their_rows():
    """Lenient means the preview still answers everything it can: the row
    keeps its readable fields, and each unreadable cell contributes one
    sentence — the Admin fixes the mapping while watching the rows."""
    export = (
        "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n"
        "01.07.2026 14:30;Belohnung;BTC;0,5;;abc-1\n"
        "gestern;Einzahlung;BTC;fünf;;abc-2\n"
    )

    answered = interpret(export, mapping())

    first, second = answered.rows
    assert first.type is None
    assert first.quantity == Decimal("0.5")
    assert first.problems == (
        "The type value 'Belohnung' is not mapped — map it, or leave it out.",
    )
    assert second.problems == (
        "The timestamp 'gestern' does not match the format '%d.%m.%Y %H:%M'.",
        "The quantity 'fünf' is not a number the mapping can read.",
    )


def test_a_mapped_column_the_file_does_not_carry_is_a_defect():
    answered = interpret(BROKER_EXPORT, mapping(quantity="Menge"))

    assert answered.defects == ("The file has no column 'Menge'.",)


def test_the_preview_answers_the_first_rows_but_counts_them_all():
    export = "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n" + "".join(
        f"01.07.2026 14:30;Einzahlung;BTC;0,{n + 1};;abc-{n}\n" for n in range(25)
    )

    answered = interpret(export, mapping())

    assert len(answered.rows) == 20
    assert answered.row_count == 25


def test_without_an_identifier_column_identifiers_derive_from_row_content():
    """Deduplication needs an identifier the venue never printed: it derives
    from the row's own content — stable across re-exports, and an occurrence
    counter keeps two genuinely identical rows distinct."""
    export = (
        "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n"
        "01.07.2026 14:30;Einzahlung;BTC;0,5;;x\n"
        "01.07.2026 14:30;Einzahlung;BTC;0,5;;x\n"
        "02.07.2026 14:30;Einzahlung;BTC;0,5;;x\n"
    )

    answered = interpret(export, mapping(external_id=None))
    again = interpret(export, mapping(external_id=None))

    ids = [row.external_id for row in answered.rows]
    assert len(set(ids)) == 3
    assert ids == [row.external_id for row in again.rows]


# --- The strict parse: the CSV Connector the import flow reads through ---


def test_the_connector_parses_a_complete_file_into_normalized_rows():
    parsed = MappingConnector(mapping()).parse(BROKER_EXPORT)

    assert parsed.warnings == ()
    first, second = parsed.rows
    assert first.external_id == "abc-1"
    assert first.occurred_at == datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    assert first.type == "transfer_in"
    assert first.symbol == "BTC"
    assert first.quantity == Decimal("0.5")
    assert first.fee_quantity == Decimal("0.0001")
    assert second.type == "transfer_out"


def test_rows_the_mapping_leaves_out_are_counted_aloud_never_silent():
    """A type value mapped to leave-out and a row moving no amount both stay
    out of the import — each stated in a warning, so a skipped row is a fact
    the Admin reads, not a hole."""
    export = (
        "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n"
        "01.07.2026 14:30;Einzahlung;BTC;0,5;;abc-1\n"
        "01.07.2026 15:00;Storno;BTC;0,1;;abc-2\n"
        "01.07.2026 16:00;Storno;BTC;0,2;;abc-3\n"
        "01.07.2026 17:00;Einzahlung;BTC;0;;abc-4\n"
    )
    with_leave_out = mapping(
        type_values={"Einzahlung": "transfer_in", "Storno": ""},
    )

    parsed = MappingConnector(with_leave_out).parse(export)

    assert [row.external_id for row in parsed.rows] == ["abc-1"]
    assert parsed.warnings == (
        "3 rows left out: 'Storno' is mapped to be left out x2, moved no amount x1.",
    )


def test_the_connector_refuses_an_incomplete_mapping_with_its_defects():
    try:
        MappingConnector(mapping(quantity=None)).parse(BROKER_EXPORT)
    except FileRejectedError as refused:
        assert str(refused) == "No column is assigned to the quantity."
    else:
        raise AssertionError("The parse accepted an incomplete mapping.")


def test_the_connector_refuses_a_row_the_mapping_cannot_read_naming_it():
    """Strict where the preview was lenient: a cell the mapping cannot read
    refuses the whole file with the row number — mis-parsing part of a file
    writes wrong history."""
    export = (
        "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n"
        "01.07.2026 14:30;Einzahlung;BTC;0,5;;abc-1\n"
        "gestern;Einzahlung;BTC;0,5;;abc-2\n"
    )

    try:
        MappingConnector(mapping()).parse(export)
    except FileRejectedError as refused:
        assert str(refused) == (
            "Row 2: The timestamp 'gestern' does not match the format '%d.%m.%Y %H:%M'."
        )
    else:
        raise AssertionError("The parse accepted a row it cannot read.")


def test_a_format_with_an_offset_converts_each_row_by_its_own_offset():
    export = "When,Amount\n2026-07-01 14:30 +0200,1.5\n2026-07-01 14:30 -0500,2\n"
    offset_mapping = ColumnMapping(
        occurred_at="When",
        datetime_format="%Y-%m-%d %H:%M %z",
        quantity="Amount",
        fixed_symbol="BTC",
        fixed_type="transfer_in",
    )

    parsed = MappingConnector(offset_mapping).parse(export)

    first, second = parsed.rows
    assert first.occurred_at == datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    assert second.occurred_at == datetime(2026, 7, 1, 19, 30, tzinfo=UTC)
    assert first.symbol == "BTC"
    assert first.type == "transfer_in"


def test_interpret_collects_the_type_columns_distinct_values_across_the_whole_file():
    """The mapping screen builds its translation rows from these — collected
    over every row, not just the previewed ones, so a value first appearing
    deep in the file still gets its row."""
    export = "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n" + "".join(
        f"01.07.2026 14:30;Einzahlung;BTC;0,{n + 1};;abc-{n}\n" for n in range(25)
    )
    export += "01.07.2026 18:00;Belohnung;BTC;0,1;;abc-99\n"

    answered = interpret(export, mapping())

    assert answered.type_values_seen == ("Belohnung", "Einzahlung")


def test_a_delimiter_that_is_not_one_character_answers_the_defect_not_a_crash():
    """The API schema accepts any string, so the port must judge it: nothing
    is read under a delimiter the Admin never declared cleanly."""
    for delimiter in (";;", ""):
        answered = interpret(BROKER_EXPORT, mapping(delimiter=delimiter))

        assert answered.defects == ("The delimiter is a single character.",)
        assert answered.rows == ()
        assert answered.row_count == 0
