"""Writes and reads over Platforms and their Accounts.

Each creator returns the new row's id, or says why the schema refused it — the
constraints are the arbiter, so a racing duplicate loses cleanly and no caller
has to check first. Which constraint failed is read from the error rather than
guessed, because "there is no such Platform" and "that name is taken" are
different answers to the Admin. Decisions live in the service — except that a
removal reads what holds the row under the same lock it deletes under, so no
holder can arrive between the two; how a refusal is worded is still the
service's.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from psycopg import errors
from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import IntegrityError


class Refusal(Enum):
    """Why a write did not happen, in the caller's terms rather than SQL's."""

    no_such_platform = "no_such_platform"
    name_taken = "name_taken"
    no_such_account = "no_such_account"
    not_a_broker = "not_a_broker"
    not_under_a_broker = "not_under_a_broker"
    # Clearing an override that alone answers for a Depot's held positions
    # (ticket 43) — the positions would stand against an unknown.
    would_unset_a_held_depot = "would_unset_a_held_depot"


@dataclass(frozen=True)
class PlatformHolders:
    """What still sits under a Platform and so keeps it from being removed —
    by the names the Admin knows them by."""

    accounts: tuple[str, ...]
    connections: tuple[str, ...]


@dataclass(frozen=True)
class AccountHolders:
    """What keeps an Account from being removed: history recorded in it, or
    the Connection kinds paired with it as (Connection label, adapter kind)."""

    recorded: bool
    pairings: tuple[tuple[str, str], ...]


# Everything that records into an Account. Each holds it by RESTRICT; Tax Lots
# are absent because they are derived — from legs or from futures records, both
# of which are here.
_RECORDED_IN = (
    "transaction_leg",
    "import_batch",
    "futures_fill",
    "futures_position",
    "funding_payment",
    "futures_derivation_issue",
)


def create_platform(engine: Engine, *, name: str, kind: str) -> int | None:
    """A place that holds value, one row per name within its kind — one brand
    may be a bank and a broker both, and those are two places."""
    try:
        with engine.begin() as connection:
            return connection.execute(
                text("INSERT INTO platform (name, kind) VALUES (:name, :kind) RETURNING id"),
                {"name": name, "kind": kind},
            ).scalar_one()
    except IntegrityError:
        return None


def rename_platform(engine: Engine, platform_id: int, *, name: str) -> Refusal | None:
    """Overwrite a Platform's name — a label nothing refers to it by, so no
    row anywhere else moves and nothing it holds stands in the way. None means
    it was renamed; a name another Platform of its kind already has loses to
    the same constraint a registration would."""
    try:
        with engine.begin() as connection:
            renamed = connection.execute(
                text("UPDATE platform SET name = :name WHERE id = :platform_id"),
                {"name": name, "platform_id": platform_id},
            )
    except IntegrityError:
        return Refusal.name_taken
    return None if renamed.rowcount == 1 else Refusal.no_such_platform


def delete_platform(engine: Engine, platform_id: int) -> PlatformHolders | Refusal | None:
    """Remove a Platform that holds nothing. None means it is gone; otherwise
    nothing was deleted, and the answer is what holds it.

    The row is locked before it is judged: an Account or a Connection arriving
    meanwhile needs the Platform's key, so it waits and then finds no Platform
    — it can never slip in between the judgement and the delete. The RESTRICT
    foreign keys stay the backstop.
    """
    with engine.begin() as connection:
        found = connection.execute(
            text("SELECT id FROM platform WHERE id = :platform_id FOR UPDATE"),
            {"platform_id": platform_id},
        ).scalar_one_or_none()
        if found is None:
            return Refusal.no_such_platform
        accounts = connection.execute(
            text("SELECT name FROM account WHERE platform_id = :platform_id ORDER BY name, id"),
            {"platform_id": platform_id},
        ).scalars()
        connections = connection.execute(
            text(
                "SELECT label FROM connection WHERE platform_id = :platform_id ORDER BY label, id"
            ),
            {"platform_id": platform_id},
        ).scalars()
        holders = PlatformHolders(accounts=tuple(accounts), connections=tuple(connections))
        if holders.accounts or holders.connections:
            return holders
        connection.execute(
            text("DELETE FROM platform WHERE id = :platform_id"), {"platform_id": platform_id}
        )
    return None


def list_platforms(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, name, kind, withholding, exemption_order_eur"
                    " FROM platform ORDER BY name, id"
                )
            ).all()
        )


def set_withholding(
    engine: Engine,
    platform_id: int,
    *,
    behaviour: str,
    exemption_order_eur: Decimal | None = None,
) -> Refusal | None:
    """Record how the broker treats income at source, and the exemption-order
    amount lodged there — one act, because the amount may only stand with the
    behaviour that gives it meaning. None means it was recorded.

    The update carries the kind in its WHERE clause, so only a broker can be
    written and the follow-up read merely names which refusal happened.
    """
    with engine.begin() as connection:
        recorded = connection.execute(
            text(
                "UPDATE platform SET withholding = :behaviour,"
                " exemption_order_eur = :exemption_order_eur"
                " WHERE id = :platform_id AND kind = 'broker'"
            ),
            {
                "behaviour": behaviour,
                "exemption_order_eur": exemption_order_eur,
                "platform_id": platform_id,
            },
        )
        if recorded.rowcount == 1:
            return None
        kind = connection.execute(
            text("SELECT kind FROM platform WHERE id = :platform_id"),
            {"platform_id": platform_id},
        ).scalar_one_or_none()
        return Refusal.no_such_platform if kind is None else Refusal.not_a_broker


def set_withholding_override(
    engine: Engine, account_id: int, *, behaviour: str | None
) -> Refusal | None:
    """State that this one Account's income is treated differently from its
    Platform's word — a brand operating through several entities — or clear
    the exception with None. None as the answer means it was recorded.

    The mirror of the leg guard: an override that alone answers for a Depot
    already holding legs may not be cleared while the Platform still states
    nothing, so the update itself refuses that case and the follow-up reads
    only name which refusal happened.
    """
    with engine.begin() as connection:
        recorded = connection.execute(
            text(
                "UPDATE account SET withholding_override = :behaviour"
                " FROM platform"
                " WHERE account.id = :account_id AND platform.id = account.platform_id"
                " AND platform.kind = 'broker'"
                " AND (CAST(:behaviour AS text) IS NOT NULL"
                "  OR platform.withholding IS NOT NULL"
                "  OR NOT EXISTS (SELECT 1 FROM transaction_leg"
                "   WHERE transaction_leg.account_id = account.id))"
            ),
            {"behaviour": behaviour, "account_id": account_id},
        )
        if recorded.rowcount == 1:
            return None
        under_broker = connection.execute(
            text(
                "SELECT platform.kind = 'broker' FROM account"
                " JOIN platform ON platform.id = account.platform_id"
                " WHERE account.id = :account_id"
            ),
            {"account_id": account_id},
        ).scalar_one_or_none()
        if under_broker is None:
            return Refusal.no_such_account
        return Refusal.would_unset_a_held_depot if under_broker else Refusal.not_under_a_broker


def create_account(
    engine: Engine,
    platform_id: int,
    *,
    name: str,
    chain: str | None = None,
    external_reference: str | None = None,
    access_software: str | None = None,
    base_currency: str | None = None,
) -> int | Refusal:
    """One holding under a Platform. The reference and access software are
    metadata for a human — nothing reads them as a data source.

    The insert is the existence check: a Platform that is gone by the time the
    row lands violates the foreign key, and that is reported as such instead
    of being dressed up as a duplicate name.
    """
    try:
        with engine.begin() as connection:
            return connection.execute(
                text(
                    "INSERT INTO account"
                    " (platform_id, name, chain, external_reference, access_software,"
                    " base_currency)"
                    " VALUES (:platform_id, :name, :chain, :external_reference,"
                    " :access_software, :base_currency)"
                    " RETURNING id"
                ),
                {
                    "platform_id": platform_id,
                    "name": name,
                    "chain": chain,
                    "external_reference": external_reference,
                    "access_software": access_software,
                    "base_currency": base_currency,
                },
            ).scalar_one()
    except IntegrityError as refused:
        if isinstance(refused.orig, errors.ForeignKeyViolation):
            return Refusal.no_such_platform
        return Refusal.name_taken


def delete_account(engine: Engine, account_id: int) -> AccountHolders | Refusal | None:
    """Remove an Account nothing was ever recorded in and no Connection kind
    is paired with. None means it is gone — and what the Admin declared about
    it went along by cascade; otherwise nothing was deleted, and the answer is
    what holds it.

    Locked before it is judged, like a Platform: a leg, a batch or a pairing
    arriving meanwhile needs the Account's key and waits. That matters most
    for a pairing, whose foreign key cascades — without the lock one made in
    that gap would be silently released along with the Account.
    """
    with engine.begin() as connection:
        found = connection.execute(
            text("SELECT id FROM account WHERE id = :account_id FOR UPDATE"),
            {"account_id": account_id},
        ).scalar_one_or_none()
        if found is None:
            return Refusal.no_such_account
        recorded = connection.execute(
            text(
                "SELECT "
                + " OR ".join(
                    f"EXISTS (SELECT 1 FROM {table} WHERE account_id = :account_id)"
                    for table in _RECORDED_IN
                )
            ),
            {"account_id": account_id},
        ).scalar_one()
        pairings = connection.execute(
            text(
                "SELECT connection.label, connection_account.adapter_kind"
                " FROM connection_account"
                " JOIN connection ON connection.id = connection_account.connection_id"
                " WHERE connection_account.account_id = :account_id"
                " ORDER BY connection.label, connection_account.adapter_kind"
            ),
            {"account_id": account_id},
        ).all()
        holders = AccountHolders(
            recorded=recorded, pairings=tuple((row.label, row.adapter_kind) for row in pairings)
        )
        if holders.recorded or holders.pairings:
            return holders
        connection.execute(
            text("DELETE FROM account WHERE id = :account_id"), {"account_id": account_id}
        )
    return None


def list_accounts(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, platform_id, name, chain, external_reference, access_software,"
                    " authoritative_source, withholding_override, base_currency"
                    " FROM account ORDER BY platform_id, name, id"
                )
            ).all()
        )


def set_authoritative_source(engine: Engine, account_id: int, source: str | None) -> bool:
    """Declare which ingestion source may write into this Account — exactly
    one (ticket 31) — or clear the declaration so the next commit declares
    itself. False when there is no such Account."""
    with engine.begin() as connection:
        declared = connection.execute(
            text("UPDATE account SET authoritative_source = :source WHERE id = :account_id"),
            {"source": source, "account_id": account_id},
        )
    return declared.rowcount == 1
