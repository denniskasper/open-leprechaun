# 34 — Connections and credential encryption

**What to build:** The Admin enters a venue's credentials once, they are encrypted before they touch the database, and no endpoint ever returns them again — not masked, not partially.

**Blocked by:** 10, 03

**Status:** ready-for-agent

- [x] A Connection holds one key and secret, plus a passphrase where a venue requires it, and a free-text label
- [x] Several Connections to the same Platform are allowed
- [x] Credentials are encrypted with a key derived from the application secret; only ciphertext is stored
- [x] No endpoint returns secret material in any form — only a label, a fingerprint and a last-used timestamp
- [x] No secret is ever logged
- [x] The UI states the required scope per venue and that it must be read-only
- [x] A Connection records last success and last error per adapter kind

## Comments

Implemented as one migration (`dee230eb24c5`: `connection`, `connection_adapter_status`),
`repositories/connections.py`, `services/connections.py`, a `/connections` router, the venue
registry at `ports/venues.py`, and a Connections settings page (`/settings/connections`).

- **Encryption** (ADR-0003): the whole credential set — key, secret, passphrase — is one
  AES-GCM blob under a key HKDF-derived from the new required `APPLICATION_SECRET` setting
  (added to `.env.example`; CI inherits it via `cp .env.example .env`). No plaintext column
  exists. The fingerprint is a 12-hex-char SHA-256 digest of the API key — recognisable,
  disclosing nothing. `credentials_of` (the sync path's door, for ticket 35) is the only
  decryption route and stamps `last_used_at` as a side effect; a secret rotation surfaces as
  `CredentialsUnreadableError`, meaning re-entry.
- **Venue registry** (`ports/venues.py`): the one place venue names live on the way in.
  Each entry states the read-only scope to grant and which credential ingredients the venue
  needs (`requires_secret`, `requires_passphrase`) — Trading 212 and Bitpanda are key-only,
  OKX takes a passphrase. The service refuses a missing ingredient before anything is stored;
  the UI reads the registry for its per-venue scope callout plus the standing read-only rule.
  Entries exist ahead of their adapters (tickets 35–37, 48–49); registration works today,
  testing/sync arrives with 35.
- **No echo anywhere**: endpoints return only label, fingerprint, `last_used_at` and per-kind
  statuses. FastAPI's default 422 handler would have echoed a malformed request body — secret
  material included — back to the caller; `create_app` now strips validation errors to type,
  location and message. Tests assert no secret survives into any response, the stored bytes,
  or anything logged at DEBUG and above.
- **Per-kind status** (ADR-0004): `record_result` upserts one row per (connection, kind); an
  error keeps the last success, a success clears the error. Nothing calls it yet outside
  tests — ticket 35 owns testing and syncing, which is also when ADR-0003's "connection
  testing is not optional" is met. The UI renders kinds as signal/alarm status lines.
- Beyond the letter of the ticket: a `DELETE /connections/{id}` endpoint with a two-step
  remove in the UI (a Connection is "managed in settings", and with nothing ever displayed
  back, removal is the only recovery from a lost venue account).
- No version bump — releases have not started; this rides as `feat:` like earlier tickets.
