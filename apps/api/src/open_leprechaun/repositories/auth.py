"""Queries over the admin row, its sessions, its second factor and the login
failures. Decisions live in the service.

Reads of the admin row are ordered deterministically as defence in depth, per
ADR-0006 — the schema already guarantees at most one row exists.
"""

from dataclasses import dataclass
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


def release_login_delay(engine: Engine, address: str, now: datetime) -> None:
    """Let the address attempt again at once, keeping its failures counted.

    For an attempt that was admitted and neither failed nor finished: the
    count it added stands, so the delays that follow are no shorter for it.
    """
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE login_failure SET delayed_until = :now WHERE address = :address"),
            {"address": address, "now": now},
        )


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


@dataclass(frozen=True)
class TotpSecrets:
    """The admin row's two sealed secrets: the active one and the one
    enrollment issued but no code has proven. Either may be absent."""

    active: bytes | None
    pending: bytes | None


def read_totp_secrets(engine: Engine) -> TotpSecrets | None:
    """None when there is no admin to have any."""
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT totp_secret, totp_pending_secret FROM admin_user ORDER BY id LIMIT 1")
        ).one_or_none()
    if row is None:
        return None
    return TotpSecrets(
        active=None if row.totp_secret is None else bytes(row.totp_secret),
        pending=None if row.totp_pending_secret is None else bytes(row.totp_pending_secret),
    )


def store_pending_totp_secret(engine: Engine, sealed: bytes) -> bool:
    """Replace whatever enrollment was under way; False while a secret is
    active, or with no admin — the statement decides, so a racing activation
    cannot be enrolled over."""
    with engine.begin() as connection:
        stored = connection.execute(
            text("UPDATE admin_user SET totp_pending_secret = :sealed WHERE totp_secret IS NULL"),
            {"sealed": sealed},
        )
        return stored.rowcount == 1


def activate_totp_secret(
    engine: Engine, pending: bytes, step: int, keep_token_hash: str | None
) -> bool:
    """Promote the pending secret that was just proven and revoke every
    session but the one kept, atomically; False when that enrollment is no
    longer the pending one.

    The proving code's step is recorded as spent in the same statement.
    """
    with engine.begin() as connection:
        activated = connection.execute(
            text(
                "UPDATE admin_user SET totp_secret = totp_pending_secret, "
                "  totp_pending_secret = NULL, totp_last_step = :step "
                "WHERE totp_pending_secret = :pending AND totp_secret IS NULL"
            ),
            {"pending": pending, "step": step},
        )
        if activated.rowcount != 1:
            return False
        connection.execute(
            text("DELETE FROM admin_session WHERE token_hash IS DISTINCT FROM :keep"),
            {"keep": keep_token_hash},
        )
        return True


def spend_totp_step(engine: Engine, step: int) -> bool:
    """Record the step of a code being accepted; False when that step, or a
    later one, was already spent. One statement, so the same code presented
    twice at once is accepted once."""
    with engine.begin() as connection:
        spent = connection.execute(
            text(
                "UPDATE admin_user SET totp_last_step = :step "
                "WHERE totp_secret IS NOT NULL "
                "AND (totp_last_step IS NULL OR totp_last_step < :step)"
            ),
            {"step": step},
        )
        return spent.rowcount == 1


def clear_totp(engine: Engine) -> bool:
    """Remove the second factor, active and pending both; False when there
    was none to remove."""
    with engine.begin() as connection:
        cleared = connection.execute(
            text(
                "UPDATE admin_user SET totp_secret = NULL, totp_pending_secret = NULL, "
                "  totp_last_step = NULL "
                "WHERE totp_secret IS NOT NULL OR totp_pending_secret IS NOT NULL"
            )
        )
        return cleared.rowcount == 1
