"""Sealing a secret for the database (ADR-0003).

AES-GCM under a key derived from the application secret, which is held outside
the database: only ciphertext reaches a column. Each kind of secret names its
own derivation context, so the one application secret feeds separate keys and
ciphertext of one kind never opens as another.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from open_leprechaun.settings import Settings

_NONCE_BYTES = 12


class UnreadableError(Exception):
    """The stored ciphertext does not open under the current application secret."""


def seal(settings: Settings, context: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    return nonce + AESGCM(_key(settings, context)).encrypt(nonce, plaintext, None)


def unseal(settings: Settings, context: bytes, stored: bytes) -> bytes:
    nonce, ciphertext = stored[:_NONCE_BYTES], stored[_NONCE_BYTES:]
    try:
        return AESGCM(_key(settings, context)).decrypt(nonce, ciphertext, None)
    except InvalidTag as sealed:
        raise UnreadableError from sealed


def _key(settings: Settings, context: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=context).derive(
        settings.application_secret.encode()
    )
