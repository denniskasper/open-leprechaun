# 34 — Connections and credential encryption

**What to build:** The Admin enters a venue's credentials once, they are encrypted before they touch the database, and no endpoint ever returns them again — not masked, not partially.

**Blocked by:** 10, 03

**Status:** ready-for-agent

- [ ] A Connection holds one key and secret, plus a passphrase where a venue requires it, and a free-text label
- [ ] Several Connections to the same Platform are allowed
- [ ] Credentials are encrypted with a key derived from the application secret; only ciphertext is stored
- [ ] No endpoint returns secret material in any form — only a label, a fingerprint and a last-used timestamp
- [ ] No secret is ever logged
- [ ] The UI states the required scope per venue and that it must be read-only
- [ ] A Connection records last success and last error per adapter kind
