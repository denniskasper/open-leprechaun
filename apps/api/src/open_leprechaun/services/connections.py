"""Connections: credentials in, never out (ADR-0003, ADR-0004).

Registering encrypts the whole credential set — key, secret, passphrase — as
one AES-GCM blob under a key derived from the application secret, so plaintext
exists only inside this module and only on the way in or the way out to an
adapter. What leaves towards any endpoint is a label, a fingerprint and a
last-used timestamp. The venue registry decides which ingredients a credential
needs; the schema decides everything about uniqueness and existence.

Nothing here logs, and nothing here returns secret material to a caller that
serialises — `credentials_of` exists for the sync path (ticket 35) alone, and
using it is what moves last_used_at.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import Engine

from open_leprechaun.ports.venues import VENUES
from open_leprechaun.repositories import connections as repository
from open_leprechaun.settings import Settings

_NONCE_BYTES = 12
# Fixed derivation context: the same application secret may one day feed other
# keys, and this string keeps this one its own.
_KEY_CONTEXT = b"open-leprechaun venue credentials v1"


class Refusal(Enum):
    """Why a Connection was not made or a pairing not stored, each a distinct
    answer to the Admin."""

    no_such_platform = "no_such_platform"
    label_taken = "label_taken"
    unknown_venue = "unknown_venue"
    secret_missing = "secret_missing"
    passphrase_missing = "passphrase_missing"
    no_such_connection = "no_such_connection"
    no_such_account = "no_such_account"
    foreign_platform = "foreign_platform"


@dataclass(frozen=True)
class Credentials:
    """The plaintext credential set — alive only between decryption and the
    adapter call, never stored, serialised or logged."""

    key: str
    secret: str | None
    passphrase: str | None


class CredentialsUnreadableError(Exception):
    """The ciphertext does not open under the current application secret —
    the secret changed, and this credential must be entered again (ADR-0003)."""


@dataclass(frozen=True)
class AdapterStatus:
    adapter_kind: str
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class AccountPairing:
    """Which Account one adapter kind writes into (ADR-0004) —
    configuration, kept apart from the kind's recorded results."""

    adapter_kind: str
    account_id: int


@dataclass(frozen=True)
class ConnectionOverview:
    id: int
    platform_id: int
    venue: str
    label: str
    fingerprint: str
    last_used_at: datetime | None
    statuses: tuple[AdapterStatus, ...]
    pairings: tuple[AccountPairing, ...]


def register(
    engine: Engine,
    settings: Settings,
    *,
    platform_id: int,
    venue: str,
    label: str,
    key: str,
    secret: str | None,
    passphrase: str | None,
) -> int | Refusal:
    """Encrypt and store one venue account's credentials. The registry names
    the required ingredients; a missing one is refused before anything is
    stored."""
    known = VENUES.get(venue)
    if known is None:
        return Refusal.unknown_venue
    if known.requires_secret and not secret:
        return Refusal.secret_missing
    if known.requires_passphrase and not passphrase:
        return Refusal.passphrase_missing

    created = repository.create_connection(
        engine,
        platform_id,
        venue=venue,
        label=label,
        credentials_ciphertext=_encrypt(
            settings, Credentials(key=key, secret=secret, passphrase=passphrase)
        ),
        fingerprint=_fingerprint(key),
    )
    if created is repository.Refusal.no_such_platform:
        return Refusal.no_such_platform
    if created is repository.Refusal.label_taken:
        return Refusal.label_taken
    return created


def overview(engine: Engine) -> list[ConnectionOverview]:
    statuses_of: dict[int, list[AdapterStatus]] = {}
    for row in repository.list_statuses(engine):
        statuses_of.setdefault(row.connection_id, []).append(
            AdapterStatus(
                adapter_kind=row.adapter_kind,
                last_success_at=row.last_success_at,
                last_error_at=row.last_error_at,
                last_error=row.last_error,
            )
        )
    pairings_of: dict[int, list[AccountPairing]] = {}
    for row in repository.list_pairings(engine):
        pairings_of.setdefault(row.connection_id, []).append(
            AccountPairing(adapter_kind=row.adapter_kind, account_id=row.account_id)
        )
    return [
        ConnectionOverview(
            id=row.id,
            platform_id=row.platform_id,
            venue=row.venue,
            label=row.label,
            fingerprint=row.fingerprint,
            last_used_at=row.last_used_at,
            statuses=tuple(statuses_of.get(row.id, [])),
            pairings=tuple(pairings_of.get(row.id, [])),
        )
        for row in repository.list_connections(engine)
    ]


def pair(engine: Engine, connection_id: int, adapter_kind: str, account_id: int) -> Refusal | None:
    """Point one adapter kind at the Account it writes into. The Account must
    sit under the Connection's own Platform — a venue's data landing under a
    different Platform would be a mispairing, not a choice."""
    connection = repository.connection_row(engine, connection_id)
    if connection is None:
        return Refusal.no_such_connection
    platform_id = repository.account_platform(engine, account_id)
    if platform_id is None:
        return Refusal.no_such_account
    if platform_id != connection.platform_id:
        return Refusal.foreign_platform
    refused = repository.pair_account(engine, connection_id, adapter_kind, account_id)
    if refused is repository.Refusal.no_such_connection:
        return Refusal.no_such_connection
    if refused is repository.Refusal.no_such_account:
        return Refusal.no_such_account
    return None


def unpair(engine: Engine, connection_id: int, adapter_kind: str) -> bool:
    return repository.unpair_account(engine, connection_id, adapter_kind)


def credentials_of(engine: Engine, settings: Settings, connection_id: int) -> Credentials | None:
    """The sync path's door to the plaintext — using it is what counts as
    "used", so last_used_at moves here and nowhere else. None when there is
    no such Connection."""
    ciphertext = repository.read_ciphertext(engine, connection_id)
    if ciphertext is None:
        return None
    credentials = _decrypt(settings, ciphertext)
    repository.mark_used(engine, connection_id, datetime.now(UTC))
    return credentials


def remove(engine: Engine, connection_id: int) -> bool:
    return repository.delete_connection(engine, connection_id)


def record_result(
    engine: Engine,
    connection_id: int,
    adapter_kind: str,
    *,
    error: str | None,
    covered_lookback_days: int | None = None,
) -> bool:
    """One kind's test or sync outcome, kept apart from every other kind's —
    one failing must never hide another succeeding (ADR-0004). A successful
    sync passes the days its window reached over (ticket 40), claiming
    coverage from that instant; a test passes nothing, because proving a
    credential opens the venue pulls no history."""
    at = datetime.now(UTC)
    covered_from = None
    if error is None and covered_lookback_days is not None:
        covered_from = at - timedelta(days=covered_lookback_days)
    return repository.record_result(
        engine, connection_id, adapter_kind, error=error, at=at, covered_from=covered_from
    )


def _encryption_key(settings: Settings) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=_KEY_CONTEXT).derive(
        settings.application_secret.encode()
    )


def _encrypt(settings: Settings, credentials: Credentials) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    plaintext = json.dumps(
        {
            "key": credentials.key,
            "secret": credentials.secret,
            "passphrase": credentials.passphrase,
        }
    ).encode()
    return nonce + AESGCM(_encryption_key(settings)).encrypt(nonce, plaintext, None)


def _decrypt(settings: Settings, stored: bytes) -> Credentials:
    nonce, ciphertext = stored[:_NONCE_BYTES], stored[_NONCE_BYTES:]
    try:
        plaintext = AESGCM(_encryption_key(settings)).decrypt(nonce, ciphertext, None)
    except InvalidTag as sealed:
        raise CredentialsUnreadableError(
            "The stored credential does not open under the current application"
            " secret; it must be entered again."
        ) from sealed
    fields = json.loads(plaintext)
    return Credentials(key=fields["key"], secret=fields["secret"], passphrase=fields["passphrase"])


def _fingerprint(key: str) -> str:
    """A short, deterministic digest of the API key: enough for the Admin to
    tell two credentials apart, nothing of the key itself."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]
