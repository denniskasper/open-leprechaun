# 12 — Cash Instruments and the EUR numéraire

**What to build:** Cash becomes an Instrument like any other, so a balance can be held and later spent. EUR is the numéraire whose movement is not itself a disposal; every other currency is an ordinary asset.

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] Cash is an Instrument family, held per Account like any other holding
- [ ] EUR is marked as the numéraire, and its movement creates no taxable event
- [ ] A non-EUR cash Instrument is an ordinary asset — nothing in the model treats it specially
- [ ] The numéraire is a property of configuration, not hardcoded into logic that could not express another
- [ ] Holdings can show a cash position as its own line
