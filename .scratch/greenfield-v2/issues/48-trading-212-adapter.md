# 48 — Trading 212 adapter

**What to build:** The broker port, proven by a real broker with a read-only API — trades, dividends and cash movements arrive as transactions, and positions arrive for reconciliation only.

**Blocked by:** 34, 43, 44

**Status:** ready-for-agent

- [ ] A broker adapter port with a fake, distinct from the exchange adapter port
- [ ] Trades, dividends, cash movements and fees are imported as normalized records
- [ ] Positions are used for reconciliation only, never as a substitute for transactions
- [ ] Foreign-currency trades store the original amount and currency alongside the EUR amount with the rate and rate date used
- [ ] A currency-conversion fee attaches to the leg it was charged against and inherits that leg's regime
- [ ] Read-only credentials only; the setup screen names the exact scope to grant
- [ ] The adapter declares its maximum lookback and reports the period covered
- [ ] The UI states that this broker is served by sync
- [ ] Tested against recorded fixtures
