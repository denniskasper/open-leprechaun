"""Passwords and sessions for the single admin.

The password is hashed with scrypt (RFC 7914) at an OWASP-recommended cost —
a modern memory-hard KDF from the standard library, so no extra dependency
carries the credential path. The hash records its own parameters, so the cost
can rise later without invalidating the stored credential.

Session lifetime and renewal: a session expires ``SESSION_TTL_HOURS`` (settings,
default 720 — thirty days) after its *last authenticated request*, not after
login. Every authenticated request slides the expiry forward, so renewal is
automatic while the admin keeps using the app, and an idle instance logs them
out. The token is random, returned once, and stored only as a SHA-256 digest —
a database dump does not hand out live sessions.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from open_leprechaun.repositories import auth as repository

# OWASP's scrypt cost row N=2^15, r=8, p=3: 32 MiB and tolerable interactive
# latency. maxmem must clear 128 * N * r bytes or hashlib refuses to run.
_SCRYPT_LOG2_N = 15
_SCRYPT_R = 8
_SCRYPT_P = 3
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_KEY_BYTES = 32
_TOKEN_BYTES = 32


class SetupAlreadyDoneError(Exception):
    """A second setup attempt while the admin exists."""


class SetupRequiredError(Exception):
    """A login attempt while no admin exists."""


@dataclass(frozen=True)
class IssuedSession:
    """A freshly minted session: the one time the token exists in the clear."""

    token: str
    expires_at: datetime


def setup_required(engine: Engine) -> bool:
    return repository.read_password_hash(engine) is None


def set_up_admin(engine: Engine, password: str) -> None:
    """Create the single admin; exactly once per database, ever."""
    if not repository.create_admin(engine, hash_password(password)):
        raise SetupAlreadyDoneError


def log_in(engine: Engine, password: str, ttl: timedelta) -> IssuedSession | None:
    """Verify the password and mint a session; None means a wrong password."""
    stored = repository.read_password_hash(engine)
    if stored is None:
        raise SetupRequiredError
    if not verify_password(password, stored):
        return None
    now = datetime.now(UTC)
    repository.purge_expired_sessions(engine, now)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = now + ttl
    repository.create_session(engine, _digest(token), expires_at)
    return IssuedSession(token=token, expires_at=expires_at)


def authenticate(engine: Engine, token: str, ttl: timedelta) -> bool:
    """Whether the token names a live session — renewing it as a side effect."""
    now = datetime.now(UTC)
    return repository.touch_session(engine, _digest(token), now, now + ttl)


def log_out(engine: Engine, token: str) -> None:
    repository.delete_session(engine, _digest(token))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = _scrypt(password, salt, _SCRYPT_LOG2_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_LOG2_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, log2_n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = _scrypt(password, bytes.fromhex(salt), int(log2_n), int(r), int(p))
        expected = bytes.fromhex(key)
    except ValueError:
        # A stored value hash_password never produced verifies as nothing
        # rather than crashing the login path.
        return False
    return hmac.compare_digest(candidate, expected)


def _scrypt(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=2**log2_n,
        r=r,
        p=p,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_KEY_BYTES,
    )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
