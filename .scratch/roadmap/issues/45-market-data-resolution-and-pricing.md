# 45 — Market data: resolution and pricing

**What to build:** Securities get prices. Identity resolution and pricing are separate ports, because no single free-tier provider does both well — one maps an identifier to its listings, the other fetches quotes and daily closes for a listing.

**Blocked by:** 44

**Status:** ready-for-agent

- [ ] An identifier-resolution port maps an identifier to one or more Listings, with a fake
- [ ] A pricing port supplies current quote and daily close history per Listing, with a fake
- [ ] Quotes record their currency and venue; a non-EUR quote converts by the reference-rate rule
- [ ] An Instrument no provider covers is marked unpriced and excluded from valuation with a visible note, never valued at zero
- [ ] Provider choice is configurable and at least one implementation works without a paid plan
- [ ] Listings can be entered by hand where no provider resolves them
- [ ] Tested against recorded fixtures
