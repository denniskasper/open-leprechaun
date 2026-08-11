"""Writes and reads over Platforms and their Accounts.

Each creator returns the new row's id, or says why the schema refused it — the
constraints are the arbiter, so a racing duplicate loses cleanly and no caller
has to check first. Which constraint failed is read from the error rather than
guessed, because "there is no such Platform" and "that name is taken" are
different answers to the Admin. Decisions live in the service.
"""

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
