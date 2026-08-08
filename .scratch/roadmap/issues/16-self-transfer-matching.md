# 16 — Self-transfer matching

**What to build:** Moving assets between the Admin's own Accounts stops looking like a sale and a fresh purchase. The app proposes candidate matches; the Admin confirms or rejects; a confirmed link carries basis and acquisition date across.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] Candidates are proposed by Instrument, quantity within a fee tolerance, and time window
- [ ] The Admin confirms or rejects each proposal; nothing links itself
- [ ] A confirmed link carries the original cost basis and the original acquisition date across
- [ ] The same mechanic works for a transfer between two Depots, preserving lot identity
- [ ] An unmatched transfer is visible as unmatched, never quietly treated as a disposal
