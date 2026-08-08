# 50 — eToro statement import

**What to build:** A broker served by an exported statement rather than an API, using the connector port, so the Admin sees which mode each broker uses and neither is second-class.

**Blocked by:** 32, 43, 44

**Status:** ready-for-agent

- [ ] A connector imports the broker's exported statement through preview and commit
- [ ] Buys, sells, dividends and distributions with gross, withholding and net, plus fees and cash movements, are all imported
- [ ] German tax withheld at source is recorded per event where the statement reports it
- [ ] Foreign withholding is recorded per dividend with its source country
- [ ] The connector declares the timezone and units the statement uses
- [ ] The UI states that this broker is served by import rather than sync
- [ ] Tested against recorded fixtures
