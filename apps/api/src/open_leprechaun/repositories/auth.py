"""Queries over the admin row, its sessions and the login failures. Decisions live in the service.

Reads of the admin row are ordered deterministically as defence in depth, per
ADR-0006 — the schema already guarantees at most one row exists.
"""

from datetime import datetime, timedelta

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


def replace_password_hash(engine: Engine, password_hash: str, keep_token_hash: str | None) -> None:
    """Swap the credential and revoke every session but the one kept, atomically.

    One transaction, so a leaked session can never outlive the password it was
    minted under by slipping between the two statements.
    """
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE admin_user SET password_hash = :password_hash"),
            {"password_hash": password_hash},
        )
        connection.execute(
            text("DELETE FROM admin_session WHERE token_hash IS DISTINCT FROM :keep"),
            {"keep": keep_token_hash},
        )


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


def claim_login_attempt(
    engine: Engine,
    address: str,
    now: datetime,
    *,
    first_delay: timedelta,
    longest_delay: timedelta,
    stale_after: timedelta,
) -> datetime | None:
    """Admit an attempt from the address, or answer when it may next try.

    None admits it — and has already counted it as a failure and set the next
    delay, doubling per failure up to the longest. Counting before the
    password is checked, in the one statement that decides, is what lets a
    burst of simultaneous guesses through only once: the row is the arbiter,
    and a login that then succeeds clears it. A record whose delay passed
    longer ago than `stale_after` is stale and counts from one again, whether or not
    the purge has reached it.
    """
    with engine.begin() as connection:
        admitted = connection.execute(
            text(
                "INSERT INTO login_failure AS known (address, failures, delayed_until) "
                "VALUES (:address, 1, :now + :first_delay) "
                "ON CONFLICT (address) DO UPDATE SET "
                "  failures = CASE WHEN known.delayed_until <= :stale THEN 1 "
                "    ELSE known.failures + 1 END, "
                "  delayed_until = :now + LEAST(:longest_delay, :first_delay * power(2, "
                "    CASE WHEN known.delayed_until <= :stale THEN 0 "
                # Clamped so a count grown over years cannot overflow the power.
                "      ELSE LEAST(known.failures, 30) END)) "
                "WHERE known.delayed_until <= :now "
                "RETURNING 1"
            ),
            {
                "address": address,
                "now": now,
                "first_delay": first_delay,
                "longest_delay": longest_delay,
                "stale": now - stale_after,
            },
        ).scalar_one_or_none()
        if admitted is not None:
            return None
        delayed_until = connection.execute(
            text("SELECT delayed_until FROM login_failure WHERE address = :address"),
            {"address": address},
        ).scalar_one_or_none()
        # Gone in between means a login from the address just succeeded and
        # cleared it; there is nothing left to wait for.
        return delayed_until or now


def clear_login_failures(engine: Engine, address: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM login_failure WHERE address = :address"), {"address": address}
        )


def purge_stale_login_failures(engine: Engine, stale: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM login_failure WHERE delayed_until <= :stale"),
            {"stale": stale},
        )


def delete_all_sessions(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM admin_session"))


def count_live_sessions(engine: Engine, now: datetime) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM admin_session WHERE expires_at > :now"), {"now": now}
        ).scalar_one()
