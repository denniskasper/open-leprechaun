"""Queries over the admin row and its sessions. Decisions live in the service.

Reads of the admin row are ordered deterministically as defence in depth, per
ADR-0006 — the schema already guarantees at most one row exists.
"""

from datetime import datetime

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


def read_password_hash(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT password_hash FROM admin_user ORDER BY id LIMIT 1")
        ).scalar_one_or_none()


def create_admin(engine: Engine, password_hash: str) -> bool:
    """Insert the single admin row; False when one already exists.

    The unique constraint is the arbiter (ADR-0006): a losing racer sees the
    integrity error, never a duplicate row.
    """
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO admin_user (password_hash) VALUES (:password_hash)"),
                {"password_hash": password_hash},
            )
    except IntegrityError:
        return False
    return True


def create_session(engine: Engine, token_hash: str, expires_at: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO admin_session (token_hash, admin_user_id, expires_at) "
                "SELECT :token_hash, id, :expires_at FROM admin_user ORDER BY id LIMIT 1"
            ),
            {"token_hash": token_hash, "expires_at": expires_at},
        )


def touch_session(engine: Engine, token_hash: str, now: datetime, new_expiry: datetime) -> bool:
    """Validate and renew in one statement: True only for a live session."""
    with engine.begin() as connection:
        renewed = connection.execute(
            text(
                "UPDATE admin_session SET expires_at = :new_expiry "
                "WHERE token_hash = :token_hash AND expires_at > :now"
            ),
            {"token_hash": token_hash, "now": now, "new_expiry": new_expiry},
        )
        return renewed.rowcount == 1


def delete_session(engine: Engine, token_hash: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM admin_session WHERE token_hash = :token_hash"),
            {"token_hash": token_hash},
        )


def purge_expired_sessions(engine: Engine, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM admin_session WHERE expires_at <= :now"), {"now": now})
