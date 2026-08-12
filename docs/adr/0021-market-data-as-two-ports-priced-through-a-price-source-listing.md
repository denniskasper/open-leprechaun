# Market data as two ports, priced through a price-source Listing

## Status

accepted

## Context

Securities need prices (ticket 45): a current quote for the portfolio and daily closes for
history. The spec splits market data into identifier resolution and pricing because no single
free-tier provider was expected to do both well. Independently, a security trades on many
markets in several currencies, and ADR-0010 already models each as a **Listing** — so "what is
this security worth" is underdetermined until something says *which market's* answer counts.
The crypto chain (ADR-0018) settled the serving vocabulary: fresh, stale with source and age,
or unpriced by name — never zero.

onvista (ADR-0020) turns out to cover both halves keylessly: its query endpoint maps ISIN, WKN,
ticker and name to an entity, the entity's snapshot lists every market with currency, latest
quote and notation id, and an `eod_history` endpoint answers daily closes per notation.

## Decision

Market data is **two ports, configured independently by name**:
`ports/security_resolution.py` maps an identifier to the Listings a provider knows (venue and
quote currency each), and `ports/security_prices.py` answers a current quote and daily closes
per Listing. A provider is addressed by the ledger's own attributes — ISIN, venue, quote
currency — and maps them to its internals itself; a Listing it cannot map is absent from the
answer, never an error. **`OnvistaMarketDataProvider` implements both ports** and is the
default for each; the registries in `market_data.py` make a different choice a configuration
value plus one implementation.

**The price source is a Listing flag**: at most one Listing per Instrument (a partial unique
index holds it), movable by the Admin, taken by a picked candidate's primary listing at
creation and by the first Listing added to a bare security. The pricing provider is asked for
exactly that Listing — one market's answer, never whichever the provider prefers. The venue
compares case-insensitively against the provider's market names, so a hand-entered "XETRA"
finds onvista's "Xetra" instead of silently never matching.

What the provider answers lands in `security_price` and `security_daily_close`, mirrors of the
crypto stores, converted by the reference-rate rule (ADR-0017) where quoted off-EUR — with the
quote's original currency and venue recorded beside the EUR figure. Holdings read the union of
both stores; the serving vocabulary and the report shapes are shared with the crypto chain
through `services/price_reports.py`.

## Considered Options

- **One combined market-data port.** Rejected: resolution and pricing genuinely have different
  shapes and different candidate providers; two ports keep either replaceable alone, exactly as
  the spec reasons.
- **Pricing keyed on the Instrument, provider picks the market.** Rejected: two markets quote
  the same ISIN in different currencies; a figure that cannot name its market is not
  reproducible, and the Admin could never prefer the market their broker actually trades on.
- **A `price_listing_id` column on `instrument`.** Rejected in favour of the flag with a
  partial unique index: the property "at most one per Instrument" lives in the schema either
  way, but the flag keeps Listing rows self-describing and the instruments overview join flat.
- **A fallback chain like crypto's.** Not yet: one keyless provider covers the need, and the
  service takes a single provider whose failure is served from the store — a chain can be
  reintroduced behind the same signature when a second implementation exists.

## Consequences

- Adding a market-data provider is one implementation plus a registry entry and a settings
  value; nothing outside the port learns its vocabulary.
- A security without a price-source Listing is reported unpriced *by name* in every price
  report rather than silently missing — the honest state ticket 44 left every security in.
- Quotes and backfills cost two onvista requests per ISIN (query, snapshot) plus one per
  history range; at single-Admin scale this stays trivial, and the per-call snapshot cache
  keeps a refresh linear.
- The eod_history range vocabulary (M1/M3/Y1/Y5/MAX) is onvista's; the port clips the answer
  to the requested dates, so a range widening on their side cannot widen a backfill.
