"""Writes and reads over Platforms and their Accounts.

Each creator returns the new row's id, or says why the schema refused it — the
constraints are the arbiter, so a racing duplicate loses cleanly and no caller
has to check first. Which constraint failed is read from the error rather than
guessed, because "there is no such Platform" and "that name is taken" are
different answers to the Admin. Decisions live in the service.
"""

from enum import Enum

from psycopg import errors
from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import IntegrityError


class Refusal(Enum):
    """Why a write did not happen, in the caller's terms rather than SQL's."""

    no_such_platform = "no_such_platform"
    name_taken = "name_taken"


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
            connection.execute(text("SELECT id, name, kind FROM platform ORDER BY name, id")).all()
        )


def create_account(
    engine: Engine,
    platform_id: int,
    *,
    name: str,
    chain: str | None = None,
    external_reference: str | None = None,
    access_software: str | None = None,
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
                    " (platform_id, name, chain, external_reference, access_software)"
                    " VALUES (:platform_id, :name, :chain, :external_reference, :access_software)"
                    " RETURNING id"
                ),
                {
                    "platform_id": platform_id,
                    "name": name,
                    "chain": chain,
                    "external_reference": external_reference,
                    "access_software": access_software,
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
                    " authoritative_source"
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
