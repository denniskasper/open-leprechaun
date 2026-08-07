# 38 — Address Indexer; Solana

**What to build:** The third ingestion mode, for a self-custody wallet that publishes neither an export nor an account — just a chain and an address. It is also the only mode that sees unsolicited inflows as they arrive.

**Blocked by:** 31, 10

**Status:** ready-for-agent

- [ ] An Address Indexer port takes a chain and an address and returns normalized transfers
- [ ] It requires no credentials and is read-only by nature rather than by permission
- [ ] One chain ships working end to end through preview and commit
- [ ] Inflows of unknown Instruments arrive as unacknowledged and mint no lots
- [ ] The port is distinct from the exchange and connector ports and shares no assumptions with them
- [ ] Tested against recorded fixtures
