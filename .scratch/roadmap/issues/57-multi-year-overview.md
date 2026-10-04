# 57 — Multi-year overview

**What to build:** One table per regime with a row per year, so carryforwards and trends are visible across years rather than buried in individual reports.

**Blocked by:** 27

**Status:** done

- [x] One table per regime with a row per year showing gross, offsets, allowance, taxable and tax
- [x] Carryforward in and out per category is visible per year
- [x] A year that produced a carryforward states the amount and the category; a year that consumed one states which year it came from
- [x] Years with unfinished prerequisites are marked as blocked, with the reason and a link to its fix
- [x] An opening carryforward entered from an assessment predating the ledger is shown as such

## Comments

Implemented as `services/multi_year_overview.overview` behind `GET /api/multi-year-overview`, and
the `Tax → Multi-year overview` screen at `/tax/overview`.

- **The figures are live, not frozen.** Each year is asked of the three engines' own
  `year_report`, so the overview restates no rule and answers "where do the years stand" for the
  ledger as it is now; a report still answers "what did I file". The cost is one full engine run
  per regime per year on every read — acceptable on a single-Admin instance, and the first thing
  to revisit if the screen is slow on a long ledger.
- **One row shape across the regimes**: gross, offsets, allowance (the configured limit beside
  what it actually freed), taxable, tax. A Freigrenze frees the whole total or nothing; the
  Sparerpauschbetrag is what the assessment applied. `tax_eur` is null for §23 and §22 — the rate
  is personal (ADR-0007) — and stated for §20.
- **§20 gross is every positively counted entry** (after Teilfreistellung), and offsets are gross
  less what survived the pots: in-year losses plus carryforward consumed, never netted across
  pots. The per-pot carryforward — in, consumed, produced, out, each slice naming its origin year
  and whether it is an opening balance — rides beside the row.
- **Blocked is the year's, not the regime's.** A year's blockers are its pre-flight blockers
  (ticket 25) plus whatever an engine refused over that no pre-flight check already names —
  a valuation awaited, a treaty limit unset, a reference rate out of reach. A regime the engine
  cannot state is null, never zero; a blocked year whose engines can still answer shows its
  figures, as a draft report would.
- **The years run from the first the ledger or an opening carryforward touches through the
  current Tax Year**, gaps included: a carryforward walks through an empty year, and a
  Vorabpauschale falls due in a year with no Transaction.
- The screen links a blocker only where its path is a registered screen (`resolveLabel` reads
  `navigation.ts`), so the pre-flight's `/futures` — which has no screen yet — shows its reason
  without a link that lands nowhere.
- **Two-axis review folded in**: an awaited valuation is no longer treated as named by the
  pre-flight's never-priced check — they are different gaps and each now states its reason; the
  refusal table carries its own pre-flight counterpart, so the two cannot drift apart; a losing
  §23 year states its losses in full, pinned by a test; the cent formatter moved into
  `format.ts`; the copy says Haltefrist and Sonstige Einkünfte. Left as they are: a reference
  rate out of reach links to Health, there being no screen that fixes a publication gap, and an
  exception no engine declares as a refusal still fails the request rather than being swallowed.
- No version bump — rides as `feat:` like the tickets before it.
