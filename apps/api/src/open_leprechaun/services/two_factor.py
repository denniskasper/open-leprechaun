"""The Admin's TOTP second factor (ADR-0005).

RFC 6238 as every authenticator app implements it — HMAC-SHA-1, six digits,
thirty-second steps — written against the standard library, so no extra
dependency carries the credential path. The secret is sealed like a venue
credential (ADR-0003): only ciphertext reaches the database, and the plaintext
leaves this module exactly once, in the enrollment the Admin scans.

Enrollment issues a *pending* secret; nothing is enforced until a code proves
the authenticator holds it. A code is accepted for the step it was made in and
one either side, to forgive a drifting clock, and never twice: the step of
each accepted code is recorded as spent.

**There are no recovery codes.** `remove` is the anti-lockout path, reached
only from the host (`python -m open_leprechaun.disable_two_factor`).
"""

import base64
import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode

from sqlalchemy import Engine

from open_leprechaun.repositories import auth as repository
from open_leprechaun.services import sealing
from open_leprechaun.settings import Settings

# Fixed derivation context: keeps this key apart from the venue-credential one
# although both derive from the same application secret.
_KEY_CONTEXT = b"open-leprechaun admin totp v1"
# 160 bits, the length RFC 4226 recommends and every authenticator accepts.
_SECRET_BYTES = 20
_STEP_SECONDS = 30
_DIGITS = 6
# Steps either side of now that still verify: a phone's clock drifts.
_DRIFT_STEPS = 1

_ISSUER = "Open Leprechaun"
_ACCOUNT = "admin"


class NoAdminError(Exception):
    """Enrollment attempted before setup created the admin."""


class AlreadyActiveError(Exception):
    """Enrollment attempted while a second factor is active."""


class NoEnrollmentError(Exception):
    """Activation attempted with no enrollment pending."""


class NotActiveError(Exception):
    """A disable attempted while no second factor is active."""


class WrongCodeError(Exception):
    """A code that does not verify, or one that was already used."""


@dataclass(frozen=True)
class Enrollment:
    """What the Admin puts in their authenticator: the one time the secret
    exists in the clear outside this module."""

    secret: str
    uri: str


def active(engine: Engine) -> bool:
    stored = repository.read_totp_secrets(engine)
    return stored is not None and stored.active is not None


def enroll(engine: Engine, settings: Settings) -> Enrollment:
    """Issue a fresh pending secret, replacing any enrollment left unfinished."""
    secret = secrets.token_bytes(_SECRET_BYTES)
    if not repository.store_pending_totp_secret(
        engine, sealing.seal(settings, _KEY_CONTEXT, secret)
    ):
        if repository.read_totp_secrets(engine) is None:
            raise NoAdminError
        raise AlreadyActiveError
    encoded = base64.b32encode(secret).decode()
    label = quote(f"{_ISSUER}:{_ACCOUNT}")
    # The parameters are the defaults, and deliberately left unsaid: several
    # authenticators ignore them, so stating anything else would be a promise
    # the app on the Admin's phone might not keep.
    query = urlencode({"secret": encoded, "issuer": _ISSUER}, quote_via=quote)
    return Enrollment(secret=encoded, uri=f"otpauth://totp/{label}?{query}")


def activate(
    engine: Engine, settings: Settings, code: str, now: datetime, keep_token_hash: str | None
) -> None:
    """Turn the pending enrollment on, given a code that proves it works.

    Every session but the caller's is revoked: each was opened by the password
    alone, and from here on that is no longer enough.
    """
    stored = repository.read_totp_secrets(engine)
    if stored is None or stored.pending is None:
        raise NoEnrollmentError
    step = _matching_step(_unsealed(settings, stored.pending), code, now)
    if step is None:
        raise WrongCodeError
    if not repository.activate_totp_secret(engine, stored.pending, step, keep_token_hash):
        # Enrolled again, or activated, between the read and the write.
        raise NoEnrollmentError


def verify(engine: Engine, settings: Settings, code: str, now: datetime) -> bool:
    """Whether the code proves the active second factor — spending it if so."""
    stored = repository.read_totp_secrets(engine)
    if stored is None or stored.active is None:
        return False
    step = _matching_step(_unsealed(settings, stored.active), code, now)
    return step is not None and repository.spend_totp_step(engine, step)


def remove(engine: Engine) -> bool:
    """Take the second factor away, pending enrollment included, asking
    nothing: the caller has already decided who is entitled to. False when
    there was none to remove."""
    return repository.clear_totp(engine)


def _unsealed(settings: Settings, sealed: bytes) -> bytes | None:
    try:
        return sealing.unseal(settings, _KEY_CONTEXT, sealed)
    except sealing.UnreadableError:
        # The application secret changed under the stored secret. No code can
        # verify against it; the server-side disable is the way back in.
        return None


def _matching_step(secret: bytes | None, code: str, now: datetime) -> int | None:
    """The time step the code was made in, if it is one this instant accepts."""
    if secret is None:
        return None
    # An app shows "123 456"; the Admin may type it that way.
    presented = "".join(code.split())
    current = int(now.timestamp()) // _STEP_SECONDS
    matched = None
    for step in range(current - _DRIFT_STEPS, current + _DRIFT_STEPS + 1):
        # Every candidate is compared, in constant time each.
        if hmac.compare_digest(_code_at(secret, step).encode(), presented.encode()):
            matched = step
    return matched


def _code_at(secret: bytes, step: int) -> str:
    mac = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 10**_DIGITS:0{_DIGITS}d}"
