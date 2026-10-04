# 41 — Historical price resolution on import

**What to build:** An imported row without a price gets the price that applied at its timestamp, so cost basis and income valuations are real rather than backfilled from today's price.

**Blocked by:** 31, 18

**Status:** done

- [x] Resolution uses the price at the transaction's timestamp; daily granularity is acceptable, finer preferred where available
- [x] A row whose price cannot be resolved is flagged rather than defaulted to zero
- [x] Unresolvable rows are listed in the import result
- [x] The resolved price records its provider and the timestamp it represents
- [x] An Instrument valued at zero because nothing prices it is treated as unknown, never as immaterial

## Comments

Implemented (ADR-0024). No schema change: the price an event is valued by is the stored daily
close of its Instrument for the UTC day of its instant — the `crypto_daily_close` store of
ticket 18, which already carries the provider and the day. `services/import_prices.py` resolves
a batch after it lands; `crypto_prices.resolve_daily_closes` walks the chain per day;
`fx.value_eur` reads the store.

How each criterion is held:

- **The price at the transaction's timestamp**: the close of the event's own UTC day, fetched
  on commit through the chain — one request per Instrument and provider over the days still
  open, a day the primary leaves open falling through to the fallback. Daily granularity; a
  finer store can sit behind the same rule later. The valuation rule then states §22 income,
  the basis of the lot it minted and crypto-for-crypto proceeds from that close, never from the
  last known price.
- **Flagged, not zero**: no close is ever stored for a day nothing priced, and a provider's
  zero is no answer (`in_eur`), so the row awaits a valuation in every engine. Tests pin both
  the missing close and the §22 year stating no total around it.
- **Listed in the import result**: `Committed.unpriced` — external id plus the Instruments left
  open, by id and symbol — beside `price_conditions` naming a rate limit apart from an outage.
  Served by all four commit endpoints and per kind by a Connection sync; the import screens show
  the list under the commit line, the sync line counts it and names the conditions.
- **Provider and timestamp recorded**: the close row's `source` and `close_date`, first stored
  wins, served by the existing closes endpoint.
- **Unknown, never immaterial**: valuation answers None, not zero, so no limit or threshold can
  read an unpriced inflow as small; bare movements are resolved too, so an unsolicited inflow
  nothing prices is named in the result before the Admin settles its stance.

Decisions worth recording:

- **A row states its own price** when one whole side of an exchange is cash or a stablecoin
  and the other side is one position; its exchanged legs ask no provider. Fees in a coin always
  want their close.
- **The flag is derived** — the absence of a close — so nothing second has to be kept honest.
  The scheduled crypto price update runs the same resolution over the whole ledger
  (`resolve_ledger`), hand-recorded events included, so a rate-limited import settles itself;
  the existing backfill endpoint is the repair by hand.
- **The current UTC day has no close**: `_store_closes` drops it for imports and backfills
  alike, since first-stored-wins would freeze an intraday point. An event of today awaits.
- **The `rates` fingerprint class now points at rows**: the closes an event rests on. A close
  for a day nothing happened on drifts nothing, so chart backfills do not churn reports.
- **Resolution runs after the batch commits**, so no provider failure can cost an import. A
  rate-limited provider is not asked again within the run; an outage may be one Instrument's
  alone, so the provider is asked on until three in a row. Anything else a provider raises is
  treated as its outage rather than failing a commit already written.
- `prices` is a required argument of every commit path rather than an optional one: there is
  no caller that should import without resolving. The test suite builds the default chain from
  providers that cover nothing, so no test reaches a live provider by importing a row.
- Not done here: a purchase paid in a stablecoin, foreign cash or another coin still mints its
  lot awaiting a basis — the lot derivation states a cost from numéraire legs only, and that
  gap shows as awaiting valuation in the engines, not in the import result. Securities are
  untouched; their imported rows state a cash price. Finer-than-daily prices are not attempted,
  and a provider's "close" is the last point it holds for the UTC day.

Post-review fixes (two-axis review): the partial-day close, the unguarded provider exception
after the batch lands, the multi-position stated-price rule, the bounded outage retries, the
ledger-wide resolution on the scheduled update, Instrument ids beside symbols in the result,
and price conditions on a sync's outcome all came out of the review.
- The end-to-end suite runs the real API, so an import committed there now asks the live
  providers, as the instruments screen already does; a failure only leaves rows unpriced.
- No version bump — rides as `feat:` like the tickets before it.
