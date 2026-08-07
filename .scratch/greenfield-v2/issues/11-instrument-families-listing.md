# 11 — Instrument, families, Listing

**What to build:** One **Instrument** concept covering every tradable thing, with family-specific attributes. Crypto Instruments are keyed on chain and contract so two tokens sharing a ticker can never collapse into one row.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `family` distinguishes crypto, security and cash; `type` refines it
- [ ] A crypto Instrument with a contract is keyed on chain and contract address; native coins key on symbol
- [ ] A symbol is a display label and a resolution hint, never authoritative for identity
- [ ] A **Listing** — Instrument, venue, quote currency — is its own concept, and price sources point at it
- [ ] Each Instrument keeps an identifier history so a later identifier change does not orphan anything referring to it
- [ ] Two Instruments sharing a symbol can coexist and are distinguishable in the UI
