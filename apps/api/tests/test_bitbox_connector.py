"""The BitBox connector against recorded fixtures (ticket 32, ADR-0008).

This export is the reason the port declares timezone and units: the BitBoxApp
writes timestamps from the exporting computer's local clock with no offset,
and amounts in the coin's smallest unit — a file that, taken at face value,
puts events in the wrong tax year and multiplies quantities a hundred
million times. The fixture rows are the export's own shape, including the
short US date format a real BitBoxApp writes.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from open_leprechaun.ports.bitbox import BitBoxConnector
from open_leprechaun.ports.csv_connector import FileRejectedError

HEADER = "Time,Type,Amount,Unit,Fee,Fee Unit,Address,Transaction ID,Note\n"


def export(*rows: str) -> str:
    return HEADER + "".join(rows)


def test_the_connector_declares_the_export_and_the_timezone_it_reads():
    connector = BitBoxConnector()
    assert connector.connector == "bitbox"
    assert connector.name == "BitBox"
    assert "BitBoxApp" in connector.expects
    # The BitBoxApp writes the exporting computer's local clock without an
    # offset; this instance reads it as the Admin's timezone.
    assert connector.timezone == "Europe/Berlin"


def test_sub_unit_amounts_are_normalised_to_whole_coins():
    """2 500 000 satoshi is 0.025 BTC — a sub-unit export is never taken as
    whole units."""
    parsed = BitBoxConnector().parse(
        export("2024-03-15T14:22:31+01:00,received,2500000,sat,,sat,bc1qa,tx-a,First deposit\n")
    )

    (received,) = parsed.rows
    assert received.symbol == "BTC"
    assert received.quantity == Decimal("0.025")
    assert received.type == "transfer_in"
    assert received.note == "First deposit"
    assert received.external_id == "tx-a"


def test_a_local_time_export_is_converted_to_utc_never_tagged_utc():
    """The short-format timestamps carry no offset. 21:51 on a July evening
    in Berlin is 19:51 UTC — and in January, with daylight saving off, the
    same wall-clock hour converts one hour less. Tagging either as UTC would
    shift events across midnight and, at year's edge, across tax years."""
    parsed = BitBoxConnector().parse(
        export(
            "7/26/25 21:51,received,1234567,satoshi,,,bc1qa,tx-summer,\n",
            "1/15/25 10:00,received,1000,satoshi,,,bc1qa,tx-winter,\n",
        )
    )

    summer, winter = parsed.rows
    assert summer.occurred_at == datetime(2025, 7, 26, 19, 51, tzinfo=UTC)
    assert winter.occurred_at == datetime(2025, 1, 15, 9, 0, tzinfo=UTC)


def test_an_offset_carrying_timestamp_converts_by_its_own_offset():
    parsed = BitBoxConnector().parse(
        export("2024-03-15T14:22:31+01:00,received,100,sat,,sat,bc1qa,tx-iso,\n")
    )

    (received,) = parsed.rows
    assert received.occurred_at == datetime(2024, 3, 15, 13, 22, 31, tzinfo=UTC)


def test_a_sent_transaction_carries_its_fee_as_its_own_quantity():
    """The BitBoxApp states the fee beside the amount, in the same smallest
    unit — it rides as a fee in whole coins, charged against the movement."""
    parsed = BitBoxConnector().parse(
        export("2024-02-28T09:11:07+01:00,sent,125000000,sat,5000,sat,bc1qb,tx-b,Payment\n")
    )

    (sent,) = parsed.rows
    assert sent.type == "transfer_out"
    assert sent.quantity == Decimal("1.25")
    assert sent.fee_quantity == Decimal("0.00005")


def test_a_fee_is_converted_by_its_own_declared_unit():
    """The Fee Unit column is the fee's own declaration — an empty one falls
    back to the amount's unit, and a fee stated in another coin's unit is a
    variant refused rather than silently divided by the wrong power of ten."""
    parsed = BitBoxConnector().parse(
        export("2024-02-28T09:11:07+01:00,sent,125000000,satoshi,5000,sat,bc1qb,tx-b,\n")
    )
    (sent,) = parsed.rows
    assert sent.fee_quantity == Decimal("0.00005")

    with pytest.raises(FileRejectedError) as refused:
        BitBoxConnector().parse(
            export("2024-02-28T09:11:07+01:00,sent,125000000,satoshi,5000,wei,bc1qb,tx-c,\n")
        )
    assert "fee" in str(refused.value)


def test_rows_sharing_a_transaction_id_collapse_into_one_movement():
    """One transaction may span several addresses, one row each, the fee
    stated on the first row only — it is still one movement."""
    parsed = BitBoxConnector().parse(
        export(
            "2024-01-10T12:00:00+01:00,sent,3000000,satoshi,2000,satoshi,bc1qa,tx-multi,\n",
            "2024-01-10T12:00:00+01:00,sent,1000000,satoshi,,satoshi,bc1qb,tx-multi,\n",
        )
    )

    (sent,) = parsed.rows
    assert sent.quantity == Decimal("0.04")
    assert sent.fee_quantity == Decimal("0.00002")


def test_rows_of_one_transaction_in_different_coins_are_refused():
    """The collapse sums amounts under one symbol — rows of one transaction
    naming different coins would silently sum bitcoin into ether, so that
    file is refused as a variant instead."""
    with pytest.raises(FileRejectedError) as refused:
        BitBoxConnector().parse(
            export(
                "2024-01-10T12:00:00+01:00,sent,3000000,satoshi,2000,satoshi,bc1qa,tx-mix,\n",
                "2024-01-10T12:00:00+01:00,sent,1000000,wei,,wei,0xb,tx-mix,\n",
            )
        )

    assert "one coin" in str(refused.value)


def test_a_send_to_yourself_records_only_the_network_fee():
    """The coins never left the account, so recording the amount would mint a
    phantom acquisition — only the fee is a fact, and the connector says so."""
    parsed = BitBoxConnector().parse(
        export("2023-12-31T23:59:00+01:00,sent_to_yourself,10000000,sat,1000,sat,bc1qc,tx-self,\n")
    )

    (self_transfer,) = parsed.rows
    assert self_transfer.type == "fee"
    assert self_transfer.quantity == Decimal("0.00001")
    assert self_transfer.fee_quantity is None
    assert any("network fee only" in w for w in parsed.warnings)


def test_a_send_to_yourself_without_a_fee_is_left_out_with_a_word():
    parsed = BitBoxConnector().parse(
        export("2023-12-31T23:59:00+01:00,sent_to_yourself,10000000,sat,,sat,bc1qc,tx-self,\n")
    )

    assert parsed.rows == ()
    assert any("moved nothing" in w for w in parsed.warnings)


def test_unconfirmed_transactions_are_left_out_with_a_count():
    parsed = BitBoxConnector().parse(
        export(
            ",received,100000,satoshi,,satoshi,bc1qa,tx-unconf,\n",
            "2024-06-01T10:00:00+02:00,received,200000,satoshi,,satoshi,bc1qb,tx-conf,\n",
        )
    )

    (received,) = parsed.rows
    assert received.external_id == "tx-conf"
    assert any("1 unconfirmed transaction" in w for w in parsed.warnings)


def test_a_file_that_is_not_the_bitbox_export_is_refused():
    with pytest.raises(FileRejectedError) as refused:
        BitBoxConnector().parse("Operation Date,Status,Currency Ticker\na,b,c\n")

    assert "not a BitBoxApp export" in str(refused.value)


def test_a_unit_the_connector_does_not_know_is_refused_not_mis_parsed():
    """An unknown unit means an unknown divisor — converting anyway would be
    a guess about quantities, so the file is refused explicitly."""
    with pytest.raises(FileRejectedError) as refused:
        BitBoxConnector().parse(
            export("2024-06-01T10:00:00+02:00,received,100,gwei,,gwei,0xa,tx-g,\n")
        )

    assert "'gwei'" in str(refused.value)


def test_a_transaction_type_the_connector_does_not_know_is_refused():
    with pytest.raises(FileRejectedError) as refused:
        BitBoxConnector().parse(
            export("2024-06-01T10:00:00+02:00,staked,100,sat,,sat,bc1qa,tx-s,\n")
        )

    assert "'staked'" in str(refused.value)


def test_a_timestamp_shape_the_connector_cannot_read_is_refused():
    with pytest.raises(FileRejectedError) as refused:
        BitBoxConnector().parse(export("26.07.2025 21:51,received,100,sat,,sat,bc1qa,tx-t,\n"))

    assert "cannot read the timestamp" in str(refused.value)


def test_wei_normalises_to_whole_ether():
    parsed = BitBoxConnector().parse(
        export("2024-06-01T10:00:00+02:00,received,1500000000000000000,wei,,wei,0xa,tx-e,\n")
    )

    (received,) = parsed.rows
    assert received.symbol == "ETH"
    assert received.quantity == Decimal("1.5")


def test_a_leading_byte_order_mark_is_tolerated():
    parsed = BitBoxConnector().parse(
        "﻿" + export("2024-06-01T10:00:00+02:00,received,100,sat,,sat,bc1qa,tx-bom,\n")
    )

    assert len(parsed.rows) == 1
