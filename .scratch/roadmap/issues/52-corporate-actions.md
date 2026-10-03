# 52 — Corporate actions

**What to build:** Issuer events that change a holding without a trade are recorded properly, so share counts and cost basis stay right without hand-editing lots. Where the treatment is fact-specific, the app records the event and refuses to assert one.

**Blocked by:** 19

**Status:** done

- [x] A split or reverse split rescales the quantity of every open lot by the ratio and rescales per-unit basis inversely; total basis and acquisition dates are unchanged and no taxable event arises
- [x] A capital return reduces the cost basis of open lots rather than booking income, and is reported as such
- [x] A spin-off or merger is recorded, splits the basis by a ratio the Admin supplies, and is flagged for manual review
- [x] Every corporate action shows a before-and-after preview of the affected lots before it is applied
- [x] Every corporate action is reversible
- [x] Because lots are derived, reversal is the removal of the event followed by a rebuild
- [x] An Instrument's identifier history absorbs an identifier change so no lot is orphaned

## Comments

Implemented. One revision (`e4c7b9a2d1f3`) creates `corporate_action`; the engine lives in
`services/lots.py` (the derivation walks the events), the decisions in
`services/corporate_actions.py`, the screen at `/corporate-actions`.

How each criterion is held:

- **Split / reverse split**: one kind, `split`, stated as `units_new` for every `units_old` — a
  reverse split is a ratio below one. The derivation rescales every slice open at the effective
  instant; `basis_eur` and `acquired_at` are not touched, and no transaction exists for a tax
  engine to find.
- **Capital return**: `amount_per_unit_eur` comes off each open slice's basis (cents, per lot). A
  basis stops at zero; the excess is named per lot (`excess_eur`) and flags the event, because
  what the excess is taxed as is not asserted.
- **Spin-off / merger**: a spin-off mints target slices at `units_new`/`units_old` carrying
  `basis_share` of each lot's basis (cents, exact remainder stays behind); a merger moves every
  slice to the target at the exchange ratio with its whole basis. Both keep the original
  acquisition instant, both stand `needs_review` until the Admin marks them reviewed, and an
  unreviewed one in effect up to a report year is a pre-flight blocker
  (`unreviewed_corporate_actions`).
- **Preview**: `POST /corporate-actions/preview` derives the ledger with the proposal walked
  beside the stored events and answers each open lot before and after — nothing is written.
  The same per-lot effects ride on every recorded event in `GET /corporate-actions`.
- **Reversible / removal and rebuild**: `DELETE /corporate-actions/{id}`. Nothing else is
  stored, so nothing else is undone; the `corporate_actions` input class now digests the table,
  so recording and removing both mark lots and reports stale.
- **Identifier change**: `PUT /securities/{id}/isin` exposes the existing `change_isin` — the
  Instrument row stays, so legs and lots are untouched and the superseded ISIN still resolves.

Decisions worth recording:

- **Events act on the open remainder, not on `tax_lot`**: a stored lot stays the acquisition as
  its leg minted it (the table never reflected consumption either). What an event did is read
  from `Derivation.remaining`, `.held` and `.effects` — which is what holdings, the disposal
  engines and the Vorabpauschale already read.
- **Quantity on the books moved into the derivation** (`Derivation.held`, replacing the
  holdings view's own leg sum): the rescaled quantity is the sum of the rescaled slices plus the
  rescaled unvouched part, so a ratio that does not divide evenly cannot leave a position
  reading as unvouched.
- **A slice keeps its trail** (`Slice.changes`): report-time engines value an awaited basis from
  the Instrument and units the slice was acquired as (`lots.origin`) and then apply what the
  events left of it (`lots.restated`); the Vorabpauschale judges each derived year in that
  year's units, under the fund the slice was a unit of then.
- **In transit**: a split or capital return reaches slices a confirmed transfer has in transit;
  a merger or spin-off leaves them — which Account the target units belong to in transit is not
  guessed.
- **A merger carries the whole basis**; the ratio the Admin supplies is the exchange ratio. A
  cash component is a separate ledger entry.
- **Scope**: securities and crypto assets (a token swap is the same event); cash is refused.
  The cash a capital return pays is a ledger entry of its own — the event only moves basis.
- **Effective instant**: an event applies before any transaction at its instant; the screen
  states a day and sends local midnight.
- Not taken: an appendix section for corporate actions in the frozen report — the report's
  figures already rest on the adjusted lots, and the events are listed with their per-lot
  effect on their own screen.
- No version bump — rides as `feat:` like its predecessors.
