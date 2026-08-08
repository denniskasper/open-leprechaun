# 44 — Security Instruments

**What to build:** The Admin can add a share or fund by searching for it, and each fund carries the classification its taxation depends on. An unknown identifier arriving by import creates the Instrument and flags it rather than dropping the row.

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] Search accepts ISIN, WKN, ticker or name and returns candidates with identifier, name, type, currency and primary listing
- [ ] Selecting a candidate creates the Instrument with its identifiers and links its price source to a Listing
- [ ] Manual creation is possible where no provider covers the instrument, and it is marked unpriced rather than valued at zero
- [ ] An imported position for an unknown identifier auto-creates the Instrument and flags it for review
- [ ] Each fund records its partial-exemption category and its distribution policy
- [ ] The partial-exemption value is prefilled from a provider where available, always overridable, with its source shown
- [ ] An unclassified fund is registered as a report-finalisation blocker with a direct action to classify it
- [ ] The UI shows the identifier alongside any ticker
