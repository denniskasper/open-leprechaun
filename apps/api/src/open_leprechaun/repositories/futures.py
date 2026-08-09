"""Writes and reads over futures fills, positions, funding and derivation
issues (ADR-0009). Fills and funding are immutable and deduplicated on
(source, external identifier) at the constraint — an overlapping re-sync
inserts nothing twice and there is no check-then-insert race. Derived
positions and issues are a materialisation swapped wholesale per source;
manual positions are the Admin's own rows in the same table, and the
service decides what may touch which.

Creates return the new row's id, or a Refusal naming which foundation was
missing — the foreign keys are the arbiter, as in the transaction ledger.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Connection, Row, text
from sqlalchemy.exc import IntegrityError


class Refusal(Enum):
    """Why a write did not happen, in the caller's terms rather than SQL's."""

    no_such_account = "no_such_account"
    no_such_instrument = "no_such_instrument"
    no_such_position = "no_such_position"
    not_manual = "not_manual"


@dataclass(frozen=True)
class NormalizedFill:
    """One futures trade execution as a port hands it over (CONTEXT.md):
    venue-agnostic, with the external identifier that — together with the
    source — forms the deduplication key. Amounts are in the contract's
    settlement currency, resolved to an Instrument before it reaches here.
    The enrichment trio is populated by venues that expose it and None
    otherwise — never a default."""

    external_id: str
    account_id: int
    symbol: str
    side: str
    price: Decimal
    size: Decimal
    fee: Decimal
    settlement_instrument_id: int
    occurred_at: datetime
    position_side: str | None = None
    reduce_only: bool | None = None
    realized: Decimal | None = None


@dataclass(frozen=True)
class NormalizedFunding:
    """One periodic financing payment, pulled separately from fills. `amount`
    is signed in the settlement currency: positive received, negative paid.
    `position_side` is enrichment like a fill's — the hedge-mode side the
    venue says the payment belongs to, None where it did not say."""

    external_id: str
    account_id: int
    symbol: str
    amount: Decimal
    settlement_instrument_id: int
    occurred_at: datetime
    position_side: str | None = None


@dataclass(frozen=True)
class FuturesPosition:
    """The one position model manual entry and derivation share (ADR-0009) —
    which write stores it decides the origin, and nothing else differs.
    `quantity` is the total opened over the position's life; `realized` and
    `fees` are in the settlement currency, kept apart so each stays
    traceable; `closed_at` is None while the position is open — a position
    that counts in no year."""

    account_id: int
    symbol: str
    side: str
    quantity: Decimal
    settlement_instrument_id: int
    opened_at: datetime
    closed_at: datetime | None
    realized: Decimal
    fees: Decimal


@dataclass(frozen=True)
class DerivationIssue:
    """One stream the fills could not reconcile, flagged for manual handling
    rather than guessed (ADR-0009). The stream derives no positions at all —
    a half truth would wear the confidence of a whole one."""

    account_id: int
    symbol: str
    position_side: str | None
    reason: str


def store_fills(connection: Connection, source: str, fills: Sequence[NormalizedFill]) -> int:
    """Insert what is new, skip what the dedupe key already holds — the
    count answered is what was actually new."""
    inserted = 0
    for fill in fills:
        inserted += connection.execute(
            text(
                "INSERT INTO futures_fill (source, external_id, account_id, symbol, side,"
                " price, size, fee, settlement_instrument_id, occurred_at, position_side,"
                " reduce_only, realized)"
                " VALUES (:source, :external_id, :account_id, :symbol, :side, :price, :size,"
                " :fee, :settlement_instrument_id, :occurred_at, :position_side, :reduce_only,"
                " :realized)"
                " ON CONFLICT ON CONSTRAINT futures_fill_dedupe DO NOTHING"
            ),
            {
                "source": source,
                "external_id": fill.external_id,
                "account_id": fill.account_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "price": fill.price,
                "size": fill.size,
                "fee": fill.fee,
                "settlement_instrument_id": fill.settlement_instrument_id,
                "occurred_at": fill.occurred_at,
                "position_side": fill.position_side,
                "reduce_only": fill.reduce_only,
                "realized": fill.realized,
            },
        ).rowcount
    return inserted


def store_funding(
    connection: Connection, source: str, payments: Sequence[NormalizedFunding]
) -> int:
    inserted = 0
    for payment in payments:
        inserted += connection.execute(
            text(
                "INSERT INTO funding_payment (source, external_id, account_id, symbol,"
                " amount, settlement_instrument_id, occurred_at, position_side)"
                " VALUES (:source, :external_id, :account_id, :symbol, :amount,"
                " :settlement_instrument_id, :occurred_at, :position_side)"
                " ON CONFLICT ON CONSTRAINT funding_payment_dedupe DO NOTHING"
            ),
            {
                "source": source,
                "external_id": payment.external_id,
                "account_id": payment.account_id,
                "symbol": payment.symbol,
                "amount": payment.amount,
                "settlement_instrument_id": payment.settlement_instrument_id,
                "occurred_at": payment.occurred_at,
                "position_side": payment.position_side,
            },
        ).rowcount
    return inserted


def fills_for_source(connection: Connection, source: str) -> list[Row]:
    """The entire stored sequence for one source, in the order derivation
    walks it — each fill's own instant, insertion order on ties."""
    return list(
        connection.execute(
            text(
                "SELECT id, source, external_id, account_id, symbol, side, price, size, fee,"
                " settlement_instrument_id, occurred_at, position_side, reduce_only, realized"
                " FROM futures_fill WHERE source = :source ORDER BY occurred_at, id"
            ),
            {"source": source},
        ).all()
    )


def replace_derived(
    connection: Connection,
    source: str,
    positions: Sequence[FuturesPosition],
    issues: Sequence[DerivationIssue],
) -> None:
    """Swap one source's derived positions and issues wholesale — the
    rebuild is idempotent because nothing of the old derivation survives.
    Funding attributions pointing at wiped rows go NULL by the constraint
    and are recomputed by the service right after."""
    connection.execute(
        text("DELETE FROM futures_position WHERE origin = 'derived' AND source = :source"),
        {"source": source},
    )
    connection.execute(
        text("DELETE FROM futures_derivation_issue WHERE source = :source"), {"source": source}
    )
    for position in positions:
        connection.execute(
            text(
                "INSERT INTO futures_position (origin, source, account_id, symbol, side,"
                " quantity, settlement_instrument_id, opened_at, closed_at, realized, fees)"
                " VALUES ('derived', :source, :account_id, :symbol, :side, :quantity,"
                " :settlement_instrument_id, :opened_at, :closed_at, :realized, :fees)"
            ),
            {"source": source, **_position_values(position)},
        )
    for issue in issues:
        connection.execute(
            text(
                "INSERT INTO futures_derivation_issue"
                " (source, account_id, symbol, position_side, reason)"
                " VALUES (:source, :account_id, :symbol, :position_side, :reason)"
            ),
            {
                "source": source,
                "account_id": issue.account_id,
                "symbol": issue.symbol,
                "position_side": issue.position_side,
                "reason": issue.reason,
            },
        )


def insert_manual(connection: Connection, position: FuturesPosition) -> int:
    return connection.execute(
        text(
            "INSERT INTO futures_position (origin, source, account_id, symbol, side, quantity,"
            " settlement_instrument_id, opened_at, closed_at, realized, fees)"
            " VALUES ('manual', NULL, :account_id, :symbol, :side, :quantity,"
            " :settlement_instrument_id, :opened_at, :closed_at, :realized, :fees)"
            " RETURNING id"
        ),
        _position_values(position),
    ).scalar_one()


def update_manual(connection: Connection, position_id: int, position: FuturesPosition) -> bool:
    """Revise a manual position wholesale. False when no manual row has the
    id — the caller distinguishes absent from derived before coming here."""
    revised = connection.execute(
        text(
            "UPDATE futures_position SET account_id = :account_id, symbol = :symbol,"
            " side = :side, quantity = :quantity,"
            " settlement_instrument_id = :settlement_instrument_id, opened_at = :opened_at,"
            " closed_at = :closed_at, realized = :realized, fees = :fees"
            " WHERE id = :position_id AND origin = 'manual'"
        ),
        {"position_id": position_id, **_position_values(position)},
    )
    return revised.rowcount == 1


def delete_position(connection: Connection, position_id: int) -> bool:
    removed = connection.execute(
        text("DELETE FROM futures_position WHERE id = :position_id AND origin = 'manual'"),
        {"position_id": position_id},
    )
    return removed.rowcount == 1


def position_origin(connection: Connection, position_id: int) -> str | None:
    return connection.execute(
        text("SELECT origin FROM futures_position WHERE id = :position_id"),
        {"position_id": position_id},
    ).scalar_one_or_none()


def position_rows(connection: Connection) -> list[Row]:
    """Every position — manual and derived alike — with its attributed
    funding summed beside the separately stored realised result and fees,
    newest opening first."""
    return list(
        connection.execute(
            text(
                "SELECT p.id, p.origin, p.source, p.account_id, p.symbol, p.side, p.quantity,"
                " p.settlement_instrument_id, p.opened_at, p.closed_at, p.realized, p.fees,"
                " coalesce(sum(f.amount), 0) AS funding"
                " FROM futures_position p"
                " LEFT JOIN funding_payment f ON f.position_id = p.id"
                " GROUP BY p.id ORDER BY p.opened_at DESC, p.id DESC"
            )
        ).all()
    )


def closed_position_rows(connection: Connection) -> list[Row]:
    """The positions that have a year to count in, oldest close first, each
    with its attributed funding summed — the §20 producer's whole input."""
    return list(
        connection.execute(
            text(
                "SELECT p.id, p.account_id, p.symbol, p.side, p.quantity,"
                " p.settlement_instrument_id, p.opened_at, p.closed_at, p.realized, p.fees,"
                " coalesce(sum(f.amount), 0) AS funding"
                " FROM futures_position p"
                " LEFT JOIN funding_payment f ON f.position_id = p.id"
                " WHERE p.closed_at IS NOT NULL"
                " GROUP BY p.id ORDER BY p.closed_at, p.id"
            )
        ).all()
    )


def attribution_inputs(connection: Connection) -> tuple[list[Row], list[Row]]:
    """What attribution needs and nothing more: every position's open
    interval and every payment's instant."""
    positions = list(
        connection.execute(
            text(
                "SELECT id, account_id, symbol, side, opened_at, closed_at"
                " FROM futures_position ORDER BY id"
            )
        ).all()
    )
    payments = list(
        connection.execute(
            text(
                "SELECT id, account_id, symbol, occurred_at, position_side"
                " FROM funding_payment ORDER BY id"
            )
        ).all()
    )
    return positions, payments


def set_attributions(connection: Connection, attributions: dict[int, int | None]) -> None:
    if not attributions:
        return
    connection.execute(
        text("UPDATE funding_payment SET position_id = :position_id WHERE id = :payment_id"),
        [
            {"payment_id": payment_id, "position_id": position_id}
            for payment_id, position_id in attributions.items()
        ],
    )


def unattributable_rows(connection: Connection) -> list[Row]:
    """Every payment no single position could claim — stored whole, surfaced
    wherever funding is shown, never dropped."""
    return list(
        connection.execute(
            text(
                "SELECT id, source, account_id, symbol, amount, settlement_instrument_id,"
                " occurred_at, position_side FROM funding_payment WHERE position_id IS NULL"
                " ORDER BY occurred_at, id"
            )
        ).all()
    )


def issue_rows(connection: Connection) -> list[Row]:
    return list(
        connection.execute(
            text(
                "SELECT id, source, account_id, symbol, position_side, reason"
                " FROM futures_derivation_issue ORDER BY source, symbol, id"
            )
        ).all()
    )


def which_foundation_was_missing(refused: IntegrityError) -> Refusal:
    constraint = getattr(getattr(refused.orig, "diag", None), "constraint_name", None)
    if constraint == "futures_position_account_fk":
        return Refusal.no_such_account
    if constraint == "futures_position_settlement_fk":
        return Refusal.no_such_instrument
    raise refused


def _position_values(position: FuturesPosition) -> dict:
    return {
        "account_id": position.account_id,
        "symbol": position.symbol,
        "side": position.side,
        "quantity": position.quantity,
        "settlement_instrument_id": position.settlement_instrument_id,
        "opened_at": position.opened_at,
        "closed_at": position.closed_at,
        "realized": position.realized,
        "fees": position.fees,
    }
