# Venue credentials are encrypted at rest and never returned

## Status

accepted — carried from v1's ADR-0003

## Context

Syncing from exchanges and brokers requires storing an API key and secret, and sometimes a third
factor such as a passphrase. A database dump must not hand over the Admin's accounts.

## Decision

Store credentials symmetrically encrypted with a key derived from the application secret and held
outside the database. Only ciphertext reaches a column. No endpoint returns secret material in any
form — not masked, not partially, not the last four characters. The UI shows a label, a
fingerprint and a last-used timestamp, and states the read-only scope each venue requires.

## Consequences

- Plaintext secrets never touch the database or its backups.
- The encryption key becomes part of deployment and must be backed up separately; losing it means
  re-entering every credential.
- Because nothing is ever displayed back, a mistyped key is discovered by testing the connection
  rather than by reading it — connection testing is therefore not optional.
