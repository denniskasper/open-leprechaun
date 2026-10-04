"""Writes and reads over the Transaction ledger. The schema holds the shape;
whether a set of legs balances for its type is the service's decision, judged
before anything reaches here.

Creates return the new row's id, or a Refusal naming which foundation was
missing — the foreign keys are the arbiter, so there is no check-then-insert
race, and the constraint that failed decides which answer is given.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Connection, Engine, Row, text
from sqlalchemy.exc import IntegrityError


@dataclass(frozen=True)
class Leg:
    """One side of an economic event, as handed in: a fee names the sibling
    it was charged against by position, resolved to a row id on insert."""

    account_id: int
    instrument_id: int
    role: str
    quantity: Decimal
    charged_against: int | None = None


@dataclass(frozen=True)
class CapitalIncome:
    """What a dividend, distribution or interest Transaction declares beyond
    its legs (ticket 47): the security that paid, the Quellensteuer with its
    source country, and the German tax withheld at source split into its
    components. Every amount is denominated in the received leg's own
    Instrument, so the gross is the net that arrived plus everything here."""

    paying_instrument_id: int | None = None
    foreign_withholding: Decimal = Decimal(0)
    source_country: str | None = None
    kapitalertragsteuer: Decimal = Decimal(0)
    solidarity_surcharge: Decimal = Decimal(0)
    church_tax: Decimal = Decimal(0)


@dataclass(frozen=True)
class OriginalAmount:
    """What a trade settled in another currency than it was priced in states
    beside its legs (ticket 48, ADR-0025): the amount as priced, its
    currency, and the rate the broker applied — units of that currency per
    one unit of the settled currency — with the date the rate is of."""

    amount: Decimal
    currency: str
    rate: Decimal
    rate_date: date


class Refusal(Enum):
    """Why a write did not happen, in the caller's terms rather than SQL's."""

    no_such_transaction = "no_such_transaction"
    no_such_account = "no_such_account"
    no_such_instrument = "no_such_instrument"
    # A leg would land in a Depot whose withholding behaviour nothing has set
    # (ticket 43) — income there would be classified against an unknown.
    withholding_unset = "withholding_unset"


_TRANSACTION_COLUMNS = (
    "id, type, occurred_at, note, reconstructed, estimated_basis_eur, aggregate_id"
)
_LEG_COLUMNS = (
    "id, transaction_id, account_id, instrument_id, role, quantity, charged_against_leg_id"
)


def create_transaction(
    engine: Engine,
    *,
    type: str,
    occurred_at: datetime,
    note: str | None,
    legs: list[Leg],
    reconstructed: str | None = None,
    estimated_basis_eur: Decimal | None = None,
    capital_income: CapitalIncome | None = None,
) -> int | Refusal:
    try:
        with engine.begin() as connection:
            if _any_unset_depot(connection, [leg.account_id for leg in legs]):
                return Refusal.withholding_unset
            return insert_transaction(
                connection,
                type=type,
                occurred_at=occurred_at,
                note=note,
                legs=legs,
                reconstructed=reconstructed,
                estimated_basis_eur=estimated_basis_eur,
                capital_income=capital_income,
            )
    except IntegrityError as refused:
        return _which_foundation_was_missing(refused)


def insert_transaction(
    connection: Connection,
    *,
    type: str,
    occurred_at: datetime,
    note: str | None,
    legs: list[Leg],
    reconstructed: str | None = None,
    estimated_basis_eur: Decimal | None = None,
    capital_income: CapitalIncome | None = None,
    original_amount: OriginalAmount | None = None,
) -> int:
    """The insert itself, on the caller's connection — for a caller that
    writes many events atomically, as an import commit does."""
    transaction_id = connection.execute(
        text(
            "INSERT INTO transaction"
            " (type, occurred_at, note, reconstructed, estimated_basis_eur)"
            " VALUES (:type, :occurred_at, :note, :reconstructed, :estimated_basis_eur)"
            " RETURNING id"
        ),
        {
            "type": type,
            "occurred_at": occurred_at,
            "note": note,
            "reconstructed": reconstructed,
            "estimated_basis_eur": estimated_basis_eur,
        },
    ).scalar_one()
    _insert_legs(connection, transaction_id, legs)
    _insert_capital_income(connection, transaction_id, capital_income)
    if original_amount is not None:
        connection.execute(
            text(
                "INSERT INTO original_amount (transaction_id, amount, currency, rate, rate_date)"
                " VALUES (:transaction_id, :amount, :currency, :rate, :rate_date)"
            ),
            {
                "transaction_id": transaction_id,
                "amount": original_amount.amount,
                "currency": original_amount.currency,
                "rate": original_amount.rate,
                "rate_date": original_amount.rate_date,
            },
        )
    return transaction_id


def replace_transaction(
    engine: Engine,
    transaction_id: int,
    *,
    type: str,
    occurred_at: datetime,
    note: str | None,
    legs: list[Leg],
    reconstructed: str | None = None,
    estimated_basis_eur: Decimal | None = None,
    capital_income: CapitalIncome | None = None,
) -> Refusal | None:
    """Revise an event wholesale: the header updated, the legs swapped for
    the given set in one transaction. None means it was replaced."""
    try:
        with engine.begin() as connection:
            # Judged before anything is touched: a refusal returned from
            # inside this block would still commit whatever came before it.
            if _any_unset_depot(connection, [leg.account_id for leg in legs]):
                return Refusal.withholding_unset
            revised = connection.execute(
                text(
                    "UPDATE transaction SET type = :type, occurred_at = :occurred_at,"
                    " note = :note, reconstructed = :reconstructed,"
                    " estimated_basis_eur = :estimated_basis_eur"
                    " WHERE id = :transaction_id"
                ),
                {
                    "type": type,
                    "occurred_at": occurred_at,
                    "note": note,
                    "reconstructed": reconstructed,
                    "estimated_basis_eur": estimated_basis_eur,
                    "transaction_id": transaction_id,
                },
            )
            if revised.rowcount != 1:
                return Refusal.no_such_transaction
            connection.execute(
                text("DELETE FROM transaction_leg WHERE transaction_id = :transaction_id"),
                {"transaction_id": transaction_id},
            )
            _insert_legs(connection, transaction_id, legs)
            _drop_original_amount_unless_trade(connection, [transaction_id], type)
            connection.execute(
                text("DELETE FROM capital_income WHERE transaction_id = :transaction_id"),
                {"transaction_id": transaction_id},
            )
            _insert_capital_income(connection, transaction_id, capital_income)
            _mark_overridden(connection, [transaction_id])
            return None
    except IntegrityError as refused:
        return _which_foundation_was_missing(refused)


def delete_transaction(engine: Engine, transaction_id: int) -> bool:
    """Remove an event and, by cascade, its legs. False when it was not there.

    Marked overridden before the delete, so an imported row leaves a tombstone
    in the registry rather than an opening a re-import would silently refill.
    """
    with engine.begin() as connection:
        _mark_overridden(connection, [transaction_id])
        removed = connection.execute(
            text("DELETE FROM transaction WHERE id = :transaction_id"),
            {"transaction_id": transaction_id},
        )
    return removed.rowcount == 1


def reassign_account(engine: Engine, transaction_ids: list[int], account_id: int) -> Refusal | None:
    """Move every leg of the chosen events into another Account in one act —
    the repair for a file imported against the wrong holding, so a systematic
    error is not a hundred edits. None means they moved."""
    try:
        with engine.begin() as connection:
            missing = _any_missing(connection, transaction_ids)
            if missing is not None:
                return missing
            if _any_unset_depot(connection, [account_id]):
                return Refusal.withholding_unset
            connection.execute(
                text(
                    "UPDATE transaction_leg SET account_id = :account_id"
                    " WHERE transaction_id = ANY(:ids)"
                ),
                {"account_id": account_id, "ids": transaction_ids},
            )
            _mark_overridden(connection, transaction_ids)
            return None
    except IntegrityError as refused:
        return _which_foundation_was_missing(refused)


def retype(engine: Engine, transaction_ids: list[int], *, type: str) -> Refusal | None:
    """Re-type the chosen events in one act. Whether each event's legs balance
    for the new type is the service's judgement, made before this is called."""
    with engine.begin() as connection:
        missing = _any_missing(connection, transaction_ids)
        if missing is not None:
            return missing
        connection.execute(
            text("UPDATE transaction SET type = :type WHERE id = ANY(:ids)"),
            {"type": type, "ids": transaction_ids},
        )
        _drop_original_amount_unless_trade(connection, transaction_ids, type)
        _mark_overridden(connection, transaction_ids)
        return None


def _drop_original_amount_unless_trade(
    connection: Connection, transaction_ids: list[int], type: str
) -> None:
    # Only a trade states an amount as it was priced (ADR-0025); an event
    # revised into anything else no longer has a trade for it to describe.
    if type != "trade":
        connection.execute(
            text("DELETE FROM original_amount WHERE transaction_id = ANY(:ids)"),
            {"ids": transaction_ids},
        )


def _any_unset_depot(connection: Connection, account_ids: list[int]) -> bool:
    """Whether any of these Accounts sits under a broker with no effective
    withholding behaviour — the Account's own override first, the Platform's
    word second (ticket 43). Such a Depot may not hold a position, because
    income there would be classified against an unknown."""
    return connection.execute(
        text(
            "SELECT EXISTS ("
            " SELECT 1 FROM account"
            " JOIN platform ON platform.id = account.platform_id"
            " WHERE account.id = ANY(:ids) AND platform.kind = 'broker'"
            " AND COALESCE(account.withholding_override, platform.withholding) IS NULL)"
        ),
        {"ids": sorted(set(account_ids))},
    ).scalar_one()


def _any_missing(connection: Connection, transaction_ids: list[int]) -> Refusal | None:
    """Judged before anything is touched, so a bulk act is all or nothing."""
    found = connection.execute(
        text("SELECT count(DISTINCT id) FROM transaction WHERE id = ANY(:ids)"),
        {"ids": transaction_ids},
    ).scalar_one()
    if found != len(set(transaction_ids)):
        return Refusal.no_such_transaction
    return None


def _mark_overridden(connection: Connection, transaction_ids: list[int]) -> None:
    # The Admin's own hands changed an imported row: the registry keeps the
    # deduplication key but now calls the row overridden, so a re-import will
    # not silently revert the correction and a batch reversal spares it.
    connection.execute(
        text("UPDATE imported_row SET overridden = true WHERE transaction_id = ANY(:ids)"),
        {"ids": transaction_ids},
    )


def list_transactions(engine: Engine) -> list[Row]:
    """Newest first: a ledger is read from the most recent event backwards."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    f"SELECT {_TRANSACTION_COLUMNS} FROM transaction"
                    " ORDER BY occurred_at DESC, id DESC"
                )
            ).all()
        )


def list_original_amounts(engine: Engine) -> list[Row]:
    """Every original amount, keyed by the trade it is stated beside."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT transaction_id, amount, currency, rate, rate_date FROM original_amount"
                )
            ).all()
        )


def list_legs(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(f"SELECT {_LEG_COLUMNS} FROM transaction_leg ORDER BY transaction_id, id")
            ).all()
        )


def _insert_legs(connection: Connection, transaction_id: int, legs: list[Leg]) -> None:
    # Two passes: every leg first, so a fee can then attach to its sibling's
    # fresh id regardless of the order the legs arrived in.
    ids = [
        connection.execute(
            text(
                "INSERT INTO transaction_leg"
                " (transaction_id, account_id, instrument_id, role, quantity)"
                " VALUES (:transaction_id, :account_id, :instrument_id, :role, :quantity)"
                " RETURNING id"
            ),
            {
                "transaction_id": transaction_id,
                "account_id": leg.account_id,
                "instrument_id": leg.instrument_id,
                "role": leg.role,
                "quantity": leg.quantity,
            },
        ).scalar_one()
        for leg in legs
    ]
    for leg, leg_id in zip(legs, ids, strict=True):
        if leg.charged_against is not None:
            connection.execute(
                text(
                    "UPDATE transaction_leg SET charged_against_leg_id = :target WHERE id = :leg_id"
                ),
                {"target": ids[leg.charged_against], "leg_id": leg_id},
            )


_CAPITAL_INCOME_COLUMNS = (
    "paying_instrument_id, foreign_withholding, source_country,"
    " kapitalertragsteuer, solidarity_surcharge, church_tax"
)


def _insert_capital_income(
    connection: Connection, transaction_id: int, declared: CapitalIncome | None
) -> None:
    if declared is None:
        return
    connection.execute(
        text(
            f"INSERT INTO capital_income (transaction_id, {_CAPITAL_INCOME_COLUMNS})"
            " VALUES (:transaction_id, :paying_instrument_id, :foreign_withholding,"
            " :source_country, :kapitalertragsteuer, :solidarity_surcharge, :church_tax)"
        ),
        {
            "transaction_id": transaction_id,
            "paying_instrument_id": declared.paying_instrument_id,
            "foreign_withholding": declared.foreign_withholding,
            "source_country": declared.source_country,
            "kapitalertragsteuer": declared.kapitalertragsteuer,
            "solidarity_surcharge": declared.solidarity_surcharge,
            "church_tax": declared.church_tax,
        },
    )


def _which_foundation_was_missing(refused: IntegrityError) -> Refusal:
    constraint = getattr(getattr(refused.orig, "diag", None), "constraint_name", None)
    if constraint == "transaction_leg_account_fk":
        return Refusal.no_such_account
    if constraint in ("transaction_leg_instrument_fk", "capital_income_paying_instrument_fk"):
        return Refusal.no_such_instrument
    raise refused
