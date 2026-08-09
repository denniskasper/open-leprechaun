"""Writes and reads over the Tax Lot materialisation (ADR-0014): a cache of
the ledger, never a source of truth. The service derives; this module hands it
the inputs and swaps the whole table in one transaction. A lot's key is the
in-leg that minted it, so a rebuild over unchanged inputs writes literally
identical rows, and lots follow their leg by cascade — the cache can never
block a ledger edit.

Every function takes the service's Connection rather than the Engine: reads,
writes and the fingerprint stamp all share one snapshot, so nothing here can
see — or serve — a ledger the check did not cover.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Connection, Row, text


@dataclass(frozen=True)
class Lot:
    """One acquisition still on the books, keyed by the in-leg that minted it
    plus an ordinal — a confirmed self-transfer (ticket 16) may carry several
    source lots across on one in-leg, each keeping its own acquisition date.
    A coin-margined settlement (ticket 29) is minted by no in-leg — its
    `leg_id` is None, and it keys on where and when it settled:
    (account_id, instrument_id, acquired_at, ordinal).

    `basis_eur` is None while the basis awaits a valuation the ledger alone
    cannot state (tickets 17, 18); `basis_source` says how the basis was, or
    will be, determined.
    """

    leg_id: int | None
    ordinal: int
    account_id: int
    instrument_id: int
    acquired_at: datetime
    quantity: Decimal
    basis_eur: Decimal | None
    basis_source: str


def ledger(connection: Connection) -> tuple[list[Row], list[Row]]:
    """Every Transaction and every leg — the derivation's whole input, from
    the beginning of time."""
    transactions = list(
        connection.execute(
            text(
                "SELECT id, type, occurred_at, reconstructed, estimated_basis_eur"
                " FROM transaction ORDER BY occurred_at, id"
            )
        ).all()
    )
    legs = list(
        connection.execute(
            text(
                "SELECT id, transaction_id, account_id, instrument_id, role, quantity,"
                " charged_against_leg_id FROM transaction_leg ORDER BY transaction_id, id"
            )
        ).all()
    )
    return transactions, legs


def numeraire_instruments(connection: Connection) -> set[int]:
    return {
        row.id
        for row in connection.execute(text("SELECT id FROM instrument WHERE is_numeraire")).all()
    }


def stance_rows(connection: Connection) -> list[Row]:
    """Every stance decision — read here rather than through
    repositories/stances so the rebuild's snapshot covers it."""
    return list(
        connection.execute(
            text("SELECT instrument_id, account_id, stance FROM instrument_stance")
        ).all()
    )


def match_rows(connection: Connection) -> list[Row]:
    """Every confirmed self-transfer link (ticket 16) — read here rather than
    through repositories/transfer_matches so the rebuild's snapshot covers
    it. Rejections change proposals, never lots, so they are not read."""
    return list(
        connection.execute(
            text("SELECT out_leg_id, in_leg_id FROM transfer_match WHERE verdict = 'confirmed'")
        ).all()
    )


def instrument_rows(connection: Connection) -> list[Row]:
    """Each Instrument's tax-relevant classification — the family decides the
    regime a disposal falls under (§23 or §20), the numéraire designation what
    disposes at all, and the peg how a stablecoin values (ADR-0017) — plus the
    identity attributes the holdings view (ticket 20) shows. Read on the
    caller's snapshot, like every other derivation input."""
    return list(
        connection.execute(
            text(
                "SELECT id, family, type, symbol, name, chain, contract_address, isin,"
                " is_numeraire, pegged_currency FROM instrument"
            )
        ).all()
    )


def replace_all(connection: Connection, lots: list[Lot]) -> None:
    """The whole table swapped for the given derivation — never patched."""
    connection.execute(text("DELETE FROM tax_lot"))
    if lots:
        connection.execute(
            text(
                "INSERT INTO tax_lot"
                " (leg_id, ordinal, account_id, instrument_id, acquired_at, quantity,"
                " basis_eur, basis_source)"
                " VALUES (:leg_id, :ordinal, :account_id, :instrument_id, :acquired_at,"
                " :quantity, :basis_eur, :basis_source)"
            ),
            [asdict(lot) for lot in lots],
        )


def list_lots(connection: Connection) -> list[Row]:
    """Oldest acquisition first — the order FIFO consumption (21) walks.

    Takes the service's own Connection: the one read path checks the
    fingerprint and reads on a single snapshot, so no import of this module
    can quietly serve a lot nothing vouches for.
    """
    return list(
        connection.execute(
            text(
                "SELECT leg_id, ordinal, account_id, instrument_id, acquired_at, quantity,"
                " basis_eur, basis_source FROM tax_lot ORDER BY acquired_at, leg_id, ordinal"
            )
        ).all()
    )
