# 14 — Stance and the unacknowledged inbox

**What to build:** Anything arriving that the Admin has never classified waits in an inbox instead of entering the cost basis. Classifying it is a deliberate act with three outcomes.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] A new Instrument carries a **Stance** of `unacknowledged` by default
- [ ] An inflow of an unacknowledged Instrument is recorded as a transaction but mints no lot
- [ ] An inbox lists unacknowledged Instruments with the stances `kept`, `ignored` and `dangerous`
- [ ] `dangerous` applies to the Instrument globally; `ignored` and `kept` apply per Account
- [ ] Acknowledging an unsolicited inflow asks whether it was received for a counter-performance, defaulting to no
- [ ] An ignored or dangerous position stays visible with a clear warning rather than being hidden
- [ ] An ignored or dangerous Instrument can never acquire a price source
