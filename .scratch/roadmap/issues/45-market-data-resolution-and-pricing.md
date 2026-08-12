# 45 — Market data: resolution and pricing

**What to build:** Securities get prices. Identity resolution and pricing are separate ports, because no single free-tier provider does both well — one maps an identifier to its listings, the other fetches quotes and daily closes for a listing.

**Blocked by:** 44

**Status:** done

- [x] An identifier-resolution port maps an identifier to one or more Listings, with a fake
- [x] A pricing port supplies current quote and daily close history per Listing, with a fake
- [x] Quotes record their currency and venue; a non-EUR quote converts by the reference-rate rule
- [x] An Instrument no provider covers is marked unpriced and excluded from valuation with a visible note, never valued at zero
- [x] Provider choice is configurable and at least one implementation works without a paid plan
- [x] Listings can be entered by hand where no provider resolves them
- [x] Tested against recorded fixtures

## Comments

Implemented. One revision (`security_prices_and_price_source`) adds the `security_price` and
`security_daily_close` stores — mirrors of the crypto ones — and a `price_source` flag on
`listing`, at most one per Instrument under a partial unique index; existing single listings
are marked on the way up, since each was the primary listing a picked candidate vouched for.

How each criterion is held:

- **Resolution port**: `ports/security_resolution.py` — identifier in, Listings (venue, quote
  currency) out; empty is a normal answer. Faked in tests; served over
  `GET /securities/listings/resolve`.
- **Pricing port**: `ports/security_prices.py` — the price-source Listing in, a `ListingQuote`
  (price, currency, venue, as_of) or daily closes out, addressed by the ledger's own
  attributes (ISIN, venue, quote currency). A Listing the provider cannot map is absent, never
  an error. Failures reuse the crypto port's named conditions.
- **Currency and venue**: the quote carries both; the service converts off-EUR quotes and
  closes by the reference-rate rule of their own event dates (ADR-0017) and stores the original
  quote currency and venue beside the EUR figure.
- **Unpriced, never zero**: the refresh report names every priceable security — one without a
  price-source Listing or provider coverage is served `unpriced` by name, `stale` where the
  store can still speak. Holdings value securities from the store union and keep the `unpriced`
  marker and totals exclusion; a dangerous or unkept-ignored security never acquires a price
  (ADR-0012).
- **Configurable, free**: `security_resolution_provider` and `security_price_provider`
  settings, resolved through registries in `market_data.py`. `OnvistaMarketDataProvider`
  implements both ports keylessly (query → snapshot `quoteList` → `eod_history`) and is the
  default for each.
- **By hand**: `POST /securities/{id}/listings` with an optional price-source handover, and
  `PUT .../listings/{id}/price-source` to move the flag; the instruments page grew an inline
  Listings editor — held markets with the source movable, the provider's resolved markets one
  click from held, and a venue/currency form for what no provider resolves. The first Listing
  a bare security gains takes the price source.
- **Recorded fixtures**: onvista's query, snapshot and eod_history shapes recorded (trimmed,
  structurally faithful) and tested for resolution, venue-matched quoting, notation-addressed
  closes, range clipping and both failure conditions — plus verified live: quotes and closes
  for real ISINs, and the editor's fetch-markets/move-source loop exercised in the running app.

Decisions worth recording (ADR-0021): two ports over one; the price source as a Listing flag
rather than provider preference or an instrument column; a single configured provider rather
than a chain until a second implementation exists; case-insensitive venue matching so a
hand-entered "XETRA" finds onvista's "Xetra" instead of staying silently unpriced. The report
shapes and EUR-conversion guard moved to `services/price_reports.py`, shared with the crypto
chain (ticket 18) unchanged in behaviour.

Post-review fixes (two-axis review): the first-Listing-takes-the-price-source rule moved from
the web client into `add_listing` itself, so a bare security becomes priceable whoever the
caller is; the migration's backfill now marks securities' listings only; the resolved-markets
picker compares venues case-insensitively like the provider does, so a holder of "XETRA" is
not offered "Xetra" as a near-duplicate; the ADR-0012 stance-bar SQL and the
stale-or-unpriced serving now have one home each (`repositories/stances.py`,
`price_reports.served_from_store`) shared by both price paths; the onvista snapshot returns
its entity as a pair instead of a smuggled dict key; and the by-hand listing form submits on
Enter and clears only on success.
