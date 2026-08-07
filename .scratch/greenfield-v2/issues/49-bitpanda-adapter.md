# 49 — Bitpanda adapter

**What to build:** A second broker on the port, and the first Account that holds crypto and securities at once — proving that regime follows the Instrument rather than the Account.

**Blocked by:** 48

**Status:** ready-for-agent

- [ ] The adapter proves the broker port needs no change to accommodate a second venue
- [ ] Trades, dividends, cash movements and fees are imported as normalized records
- [ ] One Account holding both crypto and security Instruments works end to end
- [ ] Crypto positions in that Account are taxed under the private-sale regime and securities under the capital-income regime, with no branching on the Account
- [ ] Read-only credentials only
- [ ] Tested against recorded fixtures
