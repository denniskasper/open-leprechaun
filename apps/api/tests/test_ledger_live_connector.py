"""The Ledger Live connector against recorded fixtures (ticket 32, ADR-0008):
the operations export parsed to normalized rows — UTC timestamps, whole
units — a mismatched file refused with a sentence, and what the connector
declines to import warned about rather than dropped in silence.

The fixture rows are the export's own shape: Ledger Live writes ISO 8601 UTC
timestamps and whole coin units, and names each account with its extended
public key on every row.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from open_leprechaun.ports.csv_connector import FileRejectedError
from open_leprechaun.ports.ledger_live import LedgerLiveConnector

HEADER = (
    "Operation Date,Status,Currency Ticker,Operation Type,Operation Amount,"
    "Operation Fees,Operation Hash,Account Name,Account xpub,Countervalue Ticker,"
    "Countervalue at Operation Date,Countervalue at CSV Export\n"
)


def export(*rows: str) -> str:
    return HEADER + "".join(rows)


def test_the_connector_declares_the_export_and_the_timezone_it_reads():
    connector = LedgerLiveConnector()
    assert connector.connector == "ledger_live"
    assert connector.name == "Ledger Live"
    assert "Ledger Live" in connector.expects
    # Ledger Live writes UTC itself — the declaration says so, it does not
    # assume it.
    assert connector.timezone == "UTC"


def test_movements_and_rewards_parse_to_utc_whole_unit_rows():
    """IN, OUT and REWARD move balances the ledger tracks. Amounts are
    already whole coins and stay untouched; the Z-suffixed timestamp is the
    UTC instant it names."""
    parsed = LedgerLiveConnector().parse(
        export(
            "2022-12-04T17:49:35.000Z,Confirmed,ETH,IN,0.005,,0xaa,Ethereum 1,xp1,EUR,9,9\n",
            "2023-01-10T08:00:00.000Z,Confirmed,ETH,OUT,0.2,0.0003,0xbb,Ethereum 1,xp1,EUR,1,1\n",
            "2023-02-01T00:15:00.000Z,Confirmed,ETH,REWARD,0.01,,0xcc,Ethereum 1,xp1,EUR,1,1\n",
        )
    )

    received, sent, reward = parsed.rows
    assert received.type == "transfer_in"
    assert received.symbol == "ETH"
    assert received.quantity == Decimal("0.005")
    assert received.occurred_at == datetime(2022, 12, 4, 17, 49, 35, tzinfo=UTC)
    assert received.note == "Ethereum 1"
    assert sent.type == "transfer_out"
    assert sent.quantity == Decimal("0.2")
    assert reward.type == "staking_reward"
    assert parsed.warnings == ()


def test_an_out_movement_carries_no_separate_fee_leg():
    """Ledger Live's OUT amount is the whole balance change with the network
    fee already inside it — a separate fee leg would count the fee twice."""
    parsed = LedgerLiveConnector().parse(
        export("2023-01-10T08:00:00.000Z,Confirmed,ETH,OUT,0.2003,0.0003,0xb,E 1,x1,EUR,1,1\n")
    )

    (sent,) = parsed.rows
    assert sent.quantity == Decimal("0.2003")
    assert sent.fee_quantity is None


def test_a_file_that_is_not_the_operations_export_is_refused():
    with pytest.raises(FileRejectedError) as refused:
        LedgerLiveConnector().parse("Time,Type,Amount,Unit\n1,2,3,4\n")

    assert "not a Ledger Live operations export" in str(refused.value)


def test_an_export_spanning_several_ledger_accounts_is_refused():
    """An import lands in exactly one Account (ticket 31), and Ledger Live
    names each of its accounts by extended public key on every row — a file
    spanning several is a variant this connector refuses rather than mixing
    histories."""
    with pytest.raises(FileRejectedError) as refused:
        LedgerLiveConnector().parse(
            export(
                "2022-12-04T17:49:35.000Z,Confirmed,ETH,IN,0.005,,0xa,Ethereum 1,xpub1,EUR,9,9\n",
                "2022-12-05T17:49:35.000Z,Confirmed,BTC,IN,0.01,,0xb,Bitcoin 1,xpub2,EUR,9,9\n",
            )
        )

    assert "one account at a time" in str(refused.value)


def test_a_second_account_contributing_only_skipped_rows_still_refuses_the_file():
    """The one-account judgement reads every confirmed row, not just the
    importable ones — a second account represented only by a delegation must
    not slip a mixed export past the refusal."""
    with pytest.raises(FileRejectedError) as refused:
        LedgerLiveConnector().parse(
            export(
                "2026-08-01T10:00:00.000Z,Confirmed,NEAR,DELEGATE,221.2,,h1,NEAR 1,xp-a,USD,0,0\n",
                "2026-08-02T10:00:00.000Z,Confirmed,ETH,IN,0.1,,h2,Ethereum 1,xp-b,EUR,0,0\n",
            )
        )

    assert "one account at a time" in str(refused.value)


def test_a_timestamp_variant_the_connector_cannot_read_is_refused():
    with pytest.raises(FileRejectedError) as refused:
        LedgerLiveConnector().parse(
            export("04.12.2022 17:49,Confirmed,ETH,IN,0.005,,0xa,Ethereum 1,xpub1,EUR,9,9\n")
        )

    assert "cannot read" in str(refused.value)


def test_staking_operations_are_not_imported_and_are_named_in_a_warning():
    """Delegating does not change who owns the coins — mapping DELEGATE to a
    transfer would consume the lot and drop the holding period on a position
    that never left the Admin's control. Skipping is right; skipping quietly
    is not, because on chains where delegation moves coins to a pool contract
    the holding is no longer where the ledger says it is."""
    parsed = LedgerLiveConnector().parse(
        export(
            "2026-08-01T10:00:00.000Z,Confirmed,NEAR,DELEGATE,221.2,,h1,NEAR 1,xp,USD,0,0\n",
            "2026-08-06T10:00:00.000Z,Confirmed,NEAR,REWARD,12.5,,h2,NEAR 1,xp,USD,0,0\n",
        )
    )

    (reward,) = parsed.rows
    assert reward.type == "staking_reward"
    (warning,) = [w for w in parsed.warnings if "DELEGATE" in w]
    assert "DELEGATE (NEAR)" in warning
    assert "Ownership is unchanged" in warning


def test_other_unmapped_operations_are_warned_about_separately():
    """A skipped NFT transfer is housekeeping; a skipped delegation may mean
    the holding has moved — same mechanism, different consequence, so they do
    not share a sentence."""
    parsed = LedgerLiveConnector().parse(
        export(
            "2026-08-01T10:00:00.000Z,Confirmed,NEAR,DELEGATE,1,,h1,NEAR 1,xp,USD,0,0\n",
            "2026-08-01T11:00:00.000Z,Confirmed,NEAR,NFT_IN,1,,h2,NEAR 1,xp,USD,0,0\n",
        )
    )

    assert parsed.rows == ()
    assert any("DELEGATE (NEAR)" in w and "Ownership is unchanged" in w for w in parsed.warnings)
    assert any("NFT_IN (NEAR)" in w and "no balance change" in w for w in parsed.warnings)


def test_unconfirmed_operations_are_left_out_with_a_count():
    """A pending operation is not a fact yet — left out, and said so."""
    parsed = LedgerLiveConnector().parse(
        export(
            "2026-08-01T10:00:00.000Z,Pending,ETH,IN,0.1,,h1,Ethereum 1,xp,EUR,0,0\n",
            "2026-08-02T10:00:00.000Z,Confirmed,ETH,IN,0.2,,h2,Ethereum 1,xp,EUR,0,0\n",
        )
    )

    (received,) = parsed.rows
    assert received.quantity == Decimal("0.2")
    assert any("1 unconfirmed operation" in w for w in parsed.warnings)


def test_external_ids_are_stable_and_tell_movements_sharing_a_hash_apart():
    """Re-exporting the same history must yield the same ids — that is what
    re-import idempotency keys on — while a swap's two movements share one
    chain hash and must not collide."""
    swap = export(
        "2023-03-01T10:00:00.000Z,Confirmed,ETH,OUT,0.5,,0xswap,Ethereum 1,xp,EUR,0,0\n",
        "2023-03-01T10:00:00.000Z,Confirmed,ETH,IN,0.1,,0xswap,Ethereum 1,xp,EUR,0,0\n",
    )
    first = LedgerLiveConnector().parse(swap)
    second = LedgerLiveConnector().parse(swap)

    assert [r.external_id for r in first.rows] == [r.external_id for r in second.rows]
    out_id, in_id = (r.external_id for r in first.rows)
    assert out_id != in_id


def test_a_leading_byte_order_mark_is_tolerated():
    parsed = LedgerLiveConnector().parse(
        "﻿" + export("2022-12-04T17:49:35.000Z,Confirmed,ETH,IN,0.005,,0xa,E 1,xp,EUR,9,9\n")
    )

    assert len(parsed.rows) == 1
