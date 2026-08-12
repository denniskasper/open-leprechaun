# 18 — Crypto prices with fallback chain

**What to build:** Every crypto Instrument gets a price from some provider in a documented chain, and when they all fail the Admin sees the last known price clearly labelled stale rather than a blank or a zero.

**Blocked by:** 11

**Status:** done

- [x] A price provider port with at least two implementations and a fake, tried in documented order
- [x] No provider-specific identifier being absent may exclude an Instrument from pricing
- [x] The last known price is stored with its source and timestamp
- [x] When every provider fails, the stored price is served and clearly labelled stale
- [x] Staleness is reported by naming the affected Instruments, never as a blanket outage
- [x] A rate-limit response is surfaced as its own named condition, distinct from an outage
- [x] Daily closes are stored per Instrument with source attribution, and a backfill can populate a chosen range

## Comments

Implemented (ADR-0018). The port is `ports/crypto_prices.py`; the documented order lives in
`prices.py` — CoinGecko (`ports/coingecko.py`, quotes EUR directly), then DefiLlama
(`ports/defillama.py`, quotes USD, converted by the reference-rate rule of the quote's event
date, ADR-0017). The service (`services/crypto_prices.py`) walks the chain; storage is
`crypto_price` (last known, one row per Instrument, overwritten by fresh quotes) and
`crypto_daily_close` (immutable, first stored close per day wins), in
`repositories/crypto_prices.py`.

How each criterion is held:

- **Port, two implementations, a fake, documented order**: the protocol plus
  `FakeCryptoPriceProvider` in the tests; both real providers are tested against recorded
  responses (`httpx.MockTransport`), including 429 and outage answers. The chain order is the
  tuple in `prices.py`, injected as a FastAPI dependency so tests bind fakes without global
  state.
- **No identifier excludes**: providers map the ledger's identity attributes (chain + contract
  for tokens, symbol for natives) to their own ids; an unmapped Instrument is absent from that
  provider's answer and falls through to the next. Proven at both seams — the service test
  where the primary passes an Instrument to the fallback, and the provider tests where unmapped
  instruments trigger no request at all.
- **Last known price with source and timestamp**: `crypto_price` carries `price_eur`, `source`
  and `as_of` (the instant the quote represents, per the provider — not fetch time).
- **Stale over blank**: when every provider fails or passes an Instrument over, the stored
  price is served with `status: "stale"`; the UI (Instruments page, Price column) wears a
  caution `stale` microlabel whose title names the source and age. Nothing ever serves zero.
- **Staleness names Instruments**: the report is per-Instrument entries (fresh/stale/unpriced,
  each with symbol and name); provider conditions are a separate list, so one provider's
  failure never reads as a blanket outage.
- **Rate limit as its own condition**: `RateLimitedError` vs `ProviderOutageError` in the port,
  `rate_limited` vs `outage` in report and UI ("coingecko rate-limited · defillama outage").
- **Daily closes + backfill**: `POST /api/prices/crypto/{id}/closes/backfill` `{start, end}`
  fills the range from the first provider with history; closes store with source attribution
  and never overwrite, so a re-run cannot shift history. `GET .../closes` serves them.

Decisions worth recording:

- **`GET /api/prices/crypto` runs the chain** (and stores what it learns) rather than serving a
  cache refreshed elsewhere — the same read-fetches-and-stores shape as fx conversion, and the
  stale label derives from the refresh that just happened rather than an invented age
  threshold. Scheduled refresh belongs to ticket 42.
- **The chain prices only what the reference-rate universe cannot**: stablecoins route to their
  peg (ADR-0017), dangerous and everywhere-ignored Instruments are excluded (ADR-0012, "may
  never acquire a price source"), kept-anywhere stays priceable — all in
  `priceable_instruments`' SQL.
- **DefiLlama imports CoinGecko's native-id table** because it factually delegates native coins
  to that namespace (`coingecko:bitcoin`) — one table, documented, rather than a drifting copy.
- Verified against the live providers in the running app: the seed's BTC/SOL/UNI price fresh
  via CoinGecko; the ticker-colliding BSC token and the spam token fall through both providers
  and come back named `unpriced`; the stablecoin is absent as designed.

Post-review fixes (two-axis review):

- A provider answering a **zero price** (DefiLlama does, for dead tokens) is now "no answer" —
  the Instrument falls through to the next provider or the store — instead of tripping the
  `crypto_price_is_positive` constraint and failing the whole report.
- A quote the reference-rate universe cannot state in EUR (ECB down or a genuine rate gap)
  likewise degrades that Instrument to its stored stale price instead of erroring the report;
  a backfill skips such closes rather than failing.
- A failed price fetch on the Instruments page now shows the ErrorState pattern with retry,
  so an empty Price column is never mistaken for "the chain doesn't price this".
- The two providers' identical HTTP-and-error handling collapsed into `fetch_json` on the
  port module; `_from_store` gained a real `NamedInstrument` protocol instead of a `noqa`.
