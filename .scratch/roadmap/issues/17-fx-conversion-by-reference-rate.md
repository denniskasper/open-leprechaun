# 17 — FX conversion by reference rate

**What to build:** Every foreign-currency amount converts to EUR by one stated rule, and the conversion is reproducible years later because the rate and its date are stored alongside the result.

**Blocked by:** 11

**Status:** ready-for-agent

- [x] The euro reference rate for the relevant date is the canonical source, behind a port with a fake
- [x] Conversion uses the rate of the event date, never of report time
- [x] The rate and the date it represents are stored with every converted amount
- [x] Re-running a conversion reproduces the same figure exactly
- [x] Weekend and holiday dates resolve by one documented rule applied consistently
- [x] Stablecoin EUR values come from the daily reference rate rather than a crypto price provider

## Comments

Implemented. One revision (`115694893eed`) creates `reference_rate` and adds
`instrument.pegged_currency`; the one stated rule lives in `services/fx.py` and is pinned as
ADR-0017, with a Reference Rate entry in the glossary.

How each criterion is held:

- **Canonical source behind a port**: `ports/reference_rates.py` is the first port under
  ADR-0008 — a `ReferenceRateSource` answering the published daily rates for a currency over a
  range, as published (units of currency per euro, against the date each rate represents). The
  fake lives with the tests; the real `ports/ecb.py` hits the ECB data API's
  `EXR/D.<currency>.EUR.SP00.A` series and is tested against a recorded `csvdata` response with
  no live calls. A 404 is "no publications in the period" — a normal answer — while any other
  failure raises, so an outage is never mistaken for a gap.
- **Event date, never report time**: `convert()` derives the event date as the Europe/Berlin
  local date of the event's instant — the same clock that buckets tax years — and looks up that
  date's rate; a test holds that a later rate existing (as one always will by report time) is
  not the one used, and another that 23:30 UTC already belongs to the next Berlin day. A naive
  instant is refused.
- **Rate and date stored with the amount**: `ConvertedAmount` carries `amount_eur`, `rate` and
  `rate_date` together — the contract every persisting consumer (21, 22, 26) stores as one.
- **Reproducible exactly**: conversion fetches only when the store holds no answer for the
  event date itself — a published rate or, as a NULL row, a **checked absence** for a past day
  the ECB published nothing on — and a stored row is immutable (`ON CONFLICT DO NOTHING` — the
  first stored row wins forever). Tests convert, hand the source a revised rate, convert again
  and require the identical figure — for a published date and for a resolved absence alike.
- **Weekend and holiday rule**: a date with no publication resolves to the most recent
  publication on or before it, at most seven days back — the longest TARGET closure run is
  four days — and beyond that `RateUnavailableError` names the currency and date rather than
  resolving to a stale figure. Documented in ADR-0017; the answer's `rate_date` states which
  day's rate was actually used.
- **Stablecoins by reference rate**: `pegged_currency` on `instrument` (crypto family only, by
  CHECK) names the fiat a stablecoin tracks; `fx.reference_rate_currency` is the routing rule
  ticket 18's price chain consults before any crypto provider. The seed carries USDT pegged to
  USD.

Decisions worth recording:

- **Rates are stored as published** — units of currency per euro, never inverted on the way in —
  so the stored figure is citable against the ECB's own archive; the EUR value is the amount
  divided by the rate at Decimal's default precision.
- **The euro converts by identity** (rate 1, no source consulted): the reference-rate universe
  quotes other currencies against it, and a caller resolving a peg should not need to
  special-case a euro stablecoin.
- **No API surface and no UI** — nothing consumes conversions yet; the seam is the service, and
  inventing an endpoint here would prejudge the consumers' shape. No version bump; rides as
  `feat:` until releases start.
- **`repositories/instruments.get`** arrived as the single-row read the routing rule needs; the
  instrument column list now carries `pegged_currency` wherever a row is read.
- **An absence is only recorded for days already past in Berlin**: the current day's
  publication appears around 16:00 CET, and a conversion made before it exists must not lock
  the fallback in for later events — a same-day conversion simply asks again until the rate
  appears.
- Post-review fixes (two-axis review): the fetch trigger moved from "the whole lookback window
  is empty" to "no answer for the event date itself" — before, a rate already stored for a
  neighbouring day silently stood in for a publication the event date actually had; the checked
  absence is what keeps the corrected trigger from refetching every weekend conversion.
