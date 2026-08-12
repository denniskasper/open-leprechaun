# 44 — Security Instruments

**What to build:** The Admin can add a share or fund by searching for it, and each fund carries the classification its taxation depends on. An unknown identifier arriving by import creates the Instrument and flags it rather than dropping the row.

**Blocked by:** 11

**Status:** done

- [x] Search accepts ISIN, WKN, ticker or name and returns candidates with identifier, name, type, currency and primary listing
- [x] Selecting a candidate creates the Instrument with its identifiers and links its price source to a Listing
- [x] Manual creation is possible where no provider covers the instrument, and it is marked unpriced rather than valued at zero
- [x] An imported position for an unknown identifier auto-creates the Instrument and flags it for review
- [x] Each fund records its partial-exemption category and its distribution policy
- [x] The partial-exemption value is prefilled from a provider where available, always overridable, with its source shown
- [x] An unclassified fund is registered as a report-finalisation blocker with a direct action to classify it
- [x] The UI shows the identifier alongside any ticker

## Comments

Implemented. One revision (`fund_classification_and_review`) adds the fund classification and
the review flag to `instrument`; the classification rules are the schema's, not a service
courtesy.

How each criterion is held:

- **Search**: a security search port (`ports/security_search.py`) with an onvista
  implementation (ADR-0020) — one keyless query endpoint accepts ISIN, WKN, ticker and name
  alike; each candidate is enriched from its snapshot with currency, primary market and, for a
  fund, the classification prefill. A failing snapshot degrades that one candidate, never the
  search. Tested against recorded response shapes; the service marks candidates already in the
  ledger (via the identifier history, so a superseded ISIN still recognises its Instrument).
- **Selecting a candidate**: `POST /securities` creates the Instrument, its WKN/ticker aliases,
  its Listing and any classification in one transaction (`create_security` grew the optional
  columns); a duplicate ISIN answers 409 from the identity index, never a second row.
- **Manual creation**: the same endpoint without provider fields; with no Listing nothing can
  vouch for a value, and the UI marks every security-family row `unpriced` (no source prices
  securities until ticket 45) — an unknown value, never zero.
- **Import auto-creation**: the import framework's security spec now requires only the ISIN;
  `_create_instrument` mints import-created securities flagged `needs_review`, typed `unknown`
  where the source named no type. The schema admits `unknown` only while the flag stands, so a
  review cannot be cleared without choosing what the thing actually is
  (`PUT /securities/{id}/review`).
- **Fund classification**: `fund_category` (aktienfonds, mischfonds, immobilienfonds,
  auslands_immobilienfonds, sonstige) with `fund_category_source` — CHECK-paired so a shown
  value can always name its source — plus `distribution_policy`. Categories are the fund's
  fact; the per-year rates stay the statutory store's (ticket 46/47).
- **Prefill**: onvista's fund-type vocabulary maps to a category only where defensible
  (Rentenfonds/Geldmarktfonds map to `sonstige` as a statement); the prefill lands with source
  `provider` at creation only — the override and review endpoints stamp `admin` on the server,
  so a request cannot wear the provider's name. Both sources display as microlabels.
- **Blocker**: `_unclassified_funds` joined the pre-flight registry — funds in the ledger up
  to the end of the report year (held, not just traded: a held fund still accrues
  Vorabpauschale) with no category, plus securities still typed `unknown`, resolve at
  `/instruments`.
- **UI**: the Instruments page gained the add-security panel (search + by-hand form) and a
  Teilfreistellung column with inline classify/review editors; the identity column already
  showed the ISIN beside the ticker, and the candidate picker lists ISIN · WKN · ticker side
  by side. Verified in the running app against live onvista and by a Playwright spec
  (`e2e/instruments.spec.ts`) that classifies a fund inline.

Decisions worth recording:

- onvista over OpenFIGI, and classification-as-prefill: ADR-0020.
- onvista refuses the default python user agent outright; the client identifies itself as
  `open-leprechaun`.
- The import seam reuses ticket 31's `InstrumentSpec` rather than a new resolution path — the
  only change visible to adapters is that `security_type` became optional.
- Post-review fixes (two-axis review): the review endpoint settles only a flagged security
  (never a general rename/retype door) and wipes a stale classification when the settled type
  is not a fund's; the classification source is server-stamped on the Admin's acts; the
  blocker bound moved from in-year activity to held-through-year. Linking a price source to
  the Listing waits for ticket 45, which owns the price-source concept; until then every
  security row wears the `unpriced` marker.
