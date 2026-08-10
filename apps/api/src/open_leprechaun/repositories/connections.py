"""Writes and reads over Connections and their per-kind results.

Rows carry only ciphertext — encryption happened in the service before
anything reached here, and nothing in this module ever sees a plaintext
credential. The constraints are the arbiter as everywhere: which one failed is
read from the error, because "there is no such Platform" and "that label is
taken" are different answers to the Admin.
"""

from datetime import datetime
from enum import Enum

from psycopg import errors
from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import IntegrityError


class Refusal(Enum):
    """Why a write did not happen, in the caller's terms rather than SQL's."""

    no_such_platform = "no_such_platform"
    label_taken = "label_taken"


def create_connection(
    engine: Engine,
    platform_id: int,
    *,
    venue: str,
    label: str,
    credentials_ciphertext: bytes,
    fingerprint: str,
) -> int | Refusal:
    try:
        with engine.begin() as connection:
            return connection.execute(
                text(
                    "INSERT INTO connection"
                    " (platform_id, venue, label, credentials_ciphertext, fingerprint)"
                    " VALUES (:platform_id, :venue, :label, :ciphertext, :fingerprint)"
                    " RETURNING id"
                ),
                {
                    "platform_id": platform_id,
                    "venue": venue,
                    "label": label,
                    "ciphertext": credentials_ciphertext,
                    "fingerprint": fingerprint,
                },
            ).scalar_one()
    except IntegrityError as refused:
        if isinstance(refused.orig, errors.ForeignKeyViolation):
            return Refusal.no_such_platform
        return Refusal.label_taken


def list_connections(engine: Engine) -> list[Row]:
    """Everything the overview shows — deliberately not the ciphertext."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, platform_id, venue, label, fingerprint, last_used_at"
                    " FROM connection ORDER BY platform_id, label, id"
                )
            ).all()
        )


def read_ciphertext(engine: Engine, connection_id: int) -> bytes | None:
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT credentials_ciphertext FROM connection WHERE id = :id"),
            {"id": connection_id},
        ).scalar_one_or_none()
    return None if stored is None else bytes(stored)


def mark_used(engine: Engine, connection_id: int, used_at: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE connection SET last_used_at = :used_at WHERE id = :id"),
            {"used_at": used_at, "id": connection_id},
        )


def delete_connection(engine: Engine, connection_id: int) -> bool:
    """False when there is no such Connection. Status rows follow by cascade."""
    with engine.begin() as connection:
        deleted = connection.execute(
            text("DELETE FROM connection WHERE id = :id"), {"id": connection_id}
        )
    return deleted.rowcount == 1


def record_result(
    engine: Engine,
    connection_id: int,
    adapter_kind: str,
    *,
    error: str | None,
    at: datetime,
) -> bool:
    """Upsert one kind's outcome: a success stamps last_success_at and clears
    the error, an error stamps last_error_at and keeps the last success — the
    health panel needs both. False when there is no such Connection."""
    statement = (
        "INSERT INTO connection_adapter_status"
        " (connection_id, adapter_kind, last_success_at, last_error_at, last_error)"
        " VALUES (:connection_id, :adapter_kind, :success_at, :error_at, :error)"
        " ON CONFLICT (connection_id, adapter_kind) DO UPDATE SET"
        "  last_success_at = COALESCE(EXCLUDED.last_success_at,"
        "   connection_adapter_status.last_success_at),"
        "  last_error_at = EXCLUDED.last_error_at,"
        "  last_error = EXCLUDED.last_error"
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(statement),
                {
                    "connection_id": connection_id,
                    "adapter_kind": adapter_kind,
                    "success_at": None if error else at,
                    "error_at": at if error else None,
                    "error": error,
                },
            )
    except IntegrityError:
        return False
    return True


def list_statuses(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT connection_id, adapter_kind, last_success_at, last_error_at,"
                    " last_error"
                    " FROM connection_adapter_status ORDER BY connection_id, adapter_kind"
                )
            ).all()
        )
