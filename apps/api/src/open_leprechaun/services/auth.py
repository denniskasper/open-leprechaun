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

Throttling (ADR-0015) covers every place a credential is proven — login, and
the password and code a live session must present before a credential changes.
Each failed attempt from a source address delays that address's next attempt —
one second, doubling per failure, to at most five minutes. An attempt inside
the delay is refused before the password is looked at, so the refusal says
nothing about it. A correct password clears the address's failures, and
**nothing ever locks the account**: the longest wait between an address and
the right password is the cap. A failure record goes stale a day after its
delay ran out, and counts for nothing from then on.

The second factor (ADR-0005) is `services/two_factor.py`; this module decides
where it is demanded. While it is active, login owes a code on top of the
password, and so does every change to a credential — the password, or the
second factor itself. A wrong code is a failed attempt like a wrong password
and is throttled as one, so a leaked password does not buy unmetered guesses
at the code. A right password that still owes its code is half a login: it
may be completed at once, and clears nothing.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import Engine

from open_leprechaun.repositories import auth as repository
from open_leprechaun.services import two_factor
from open_leprechaun.settings import Settings

# OWASP's scrypt cost row N=2^15, r=8, p=3: 32 MiB and tolerable interactive
# latency. maxmem must clear 128 * N * r bytes or hashlib refuses to run.
_SCRYPT_LOG2_N = 15
_SCRYPT_R = 8
_SCRYPT_P = 3
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_KEY_BYTES = 32
_TOKEN_BYTES = 32

_FIRST_LOGIN_DELAY = timedelta(seconds=1)
_LONGEST_LOGIN_DELAY = timedelta(minutes=5)
_FAILURES_STALE_AFTER = timedelta(days=1)


class SetupAlreadyDoneError(Exception):
    """A second setup attempt while the admin exists."""


class SetupRequiredError(Exception):
    """A login or password change attempted while no admin exists."""


class WrongPasswordError(Exception):
    """A password change that could not prove the current password."""


class CodeRequiredError(Exception):
    """A credential change attempted without the code two-factor demands."""


class LoginThrottledError(Exception):
    """A login attempted while its source address is still serving a delay."""

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__(f"Login throttled for another {retry_after}.")
        self.retry_after = retry_after


class LoginRefusal(Enum):
    """Why a login minted no session, each a distinct answer to the client."""

    wrong_password = "wrong_password"
    code_required = "code_required"
    wrong_code = "wrong_code"


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


def log_in(
    engine: Engine,
    settings: Settings,
    password: str,
    code: str | None,
    *,
    address: str,
    now: datetime,
) -> IssuedSession | LoginRefusal:
    """Verify the password — and the code, while two-factor is active — and
    mint a session.

    The password is judged first: `code_required` and `wrong_code` are only
    ever said to someone who already holds it. The session is the same one
    either way; the second factor gates its issuance and changes nothing
    about it.

    Raises `LoginThrottledError` when the address is inside the delay its
    earlier failures earned — before the password is verified, so neither the
    answer nor its timing tells a right guess from a wrong one.
    """
    stored = repository.read_password_hash(engine)
    if stored is None:
        raise SetupRequiredError
    _claim_attempt(engine, address, now)
    if not verify_password(password, stored):
        return LoginRefusal.wrong_password
    if two_factor.active(engine):
        if code is None:
            # Half a login, not a failed one: the second half may follow at
            # once — a password manager fills the code in well under a second.
            # Only the delay is lifted; the attempt stays counted, so asking
            # again without a code never resets what wrong codes have earned.
            repository.release_login_delay(engine, address, now)
            return LoginRefusal.code_required
        if not two_factor.verify(engine, settings, code, now):
            return LoginRefusal.wrong_code
    repository.clear_login_failures(engine, address)
    repository.purge_expired_sessions(engine, now)
    repository.purge_stale_login_failures(engine, now - _FAILURES_STALE_AFTER)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = now + settings.session_ttl
    repository.create_session(engine, _digest(token), expires_at)
    return IssuedSession(token=token, expires_at=expires_at)


def change_password(
    engine: Engine,
    settings: Settings,
    current_password: str,
    new_password: str,
    code: str | None,
    *,
    keep_token: str | None,
    address: str,
    now: datetime,
) -> None:
    """Replace the password, revoking every session except the caller's own.

    The current password is demanded even of an authenticated caller: a
    session proves someone logged in once, not that they are at the keyboard
    now. Revoking the others is the point of a change after a suspected leak;
    keeping this one spares the admin a login straight after proving who they
    are. While two-factor is active a current code is demanded as well, or a
    stolen session and the password would together replace the credential.
    """
    _prove_identity(engine, settings, current_password, code, address=address, now=now)
    repository.replace_password_hash(
        engine, hash_password(new_password), _digest(keep_token) if keep_token else None
    )


def activate_two_factor(
    engine: Engine, settings: Settings, code: str, *, keep_token: str | None, now: datetime
) -> None:
    """Activate the pending enrollment, keeping only the caller's session."""
    two_factor.activate(engine, settings, code, now, _digest(keep_token) if keep_token else None)


def disable_two_factor(
    engine: Engine,
    settings: Settings,
    current_password: str,
    code: str,
    *,
    address: str,
    now: datetime,
) -> None:
    """Turn two-factor off, given both factors: removing one is a change to
    the credential, and is held to what changing the password is held to."""
    if not two_factor.active(engine):
        raise two_factor.NotActiveError
    _prove_identity(engine, settings, current_password, code, address=address, now=now)
    two_factor.remove(engine)


def _prove_identity(
    engine: Engine,
    settings: Settings,
    password: str,
    code: str | None,
    *,
    address: str,
    now: datetime,
) -> None:
    """Hold an authenticated caller to every factor the Admin has, before a
    credential changes. The password is judged first, as at login.

    Throttled exactly as login is, and against the same count: a session is
    no licence to guess at the password or run through the codes. Raises
    `LoginThrottledError` inside a delay, before anything is judged.
    """
    stored = repository.read_password_hash(engine)
    if stored is None:
        raise SetupRequiredError
    _claim_attempt(engine, address, now)
    if not verify_password(password, stored):
        raise WrongPasswordError
    if two_factor.active(engine):
        if code is None:
            repository.release_login_delay(engine, address, now)
            raise CodeRequiredError
        if not two_factor.verify(engine, settings, code, now):
            raise two_factor.WrongCodeError
    repository.clear_login_failures(engine, address)


def _claim_attempt(engine: Engine, address: str, now: datetime) -> None:
    """Admit one attempt at proving a credential, counting it as a failure
    until it proves otherwise; raise `LoginThrottledError` inside a delay."""
    delayed_until = repository.claim_login_attempt(
        engine,
        address,
        now,
        first_delay=_FIRST_LOGIN_DELAY,
        longest_delay=_LONGEST_LOGIN_DELAY,
        stale_after=_FAILURES_STALE_AFTER,
    )
    if delayed_until is not None:
        raise LoginThrottledError(delayed_until - now)


def authenticate(engine: Engine, token: str, ttl: timedelta) -> bool:
    """Whether the token names a live session — renewing it as a side effect."""
    now = datetime.now(UTC)
    return repository.touch_session(engine, _digest(token), now, now + ttl)


def log_out(engine: Engine, token: str) -> None:
    repository.delete_session(engine, _digest(token))


def log_out_everywhere(engine: Engine) -> None:
    repository.delete_all_sessions(engine)


def count_active_sessions(engine: Engine) -> int:
    """Sessions that would still authenticate — expired rows await the purge."""
    return repository.count_live_sessions(engine, datetime.now(UTC))


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
