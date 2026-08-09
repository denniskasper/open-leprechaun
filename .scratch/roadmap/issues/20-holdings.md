# 20 — Holdings

**What to build:** One view of everything held — crypto and cash — with quantity, average cost, current value, unrealised result and where it sits. Cost basis comes from Tax Lots, so the portfolio and the tax report cannot disagree.

**Blocked by:** 19, 17, 18

**Status:** ready-for-agent

- [x] Every position shows Instrument, family, quantity, average cost, current value, unrealised result and location
- [x] Cost basis is read from Tax Lots, never summed from inflows
- [x] Grouping by asset class, by Platform and by custody type
- [x] Cash appears as its own line
- [x] Unpriced, ignored and dangerous positions carry an explicit marker and are excluded from totals
- [x] Values render in a selected display currency; the choice never affects a tax figure
- [x] The DisplayCurrency selector itself is built here — no earlier ticket owns it
- [x] Extra software required to reach an Account is shown on its holdings
- [x] The view responds within a second at the target scale

## Comments

Implemented (ADR-0019). No migration — the portfolio derives and persists nothing. The lot
engine's `Derivation` (services/lots.py) now also returns what remains in every (Account,
Instrument) FIFO queue; `services/holdings.py` reads its basis from those remaining slices on
the same replay the disposal engine reads, so portfolio and report cannot disagree. The router
is `routers/holdings.py` (GET `/holdings`, GET `/holdings/display-rate/{currency}`), the page
`apps/web/src/pages/holdings.tsx`.

How each criterion is held:

- **Every position shows…**: one `Position` per (Account, Instrument) with nonzero leg sum,
  carrying instrument identity, family, quantity, average cost, value, unrealised result and
  Platform · Account; driven by service tests in `tests/test_holdings.py`.
- **Basis from Tax Lots**: remaining queue slices, never inflow sums — pinned by a test where a
  partial disposal leaves the second lot's basis, not the sum of both purchases. Where the lots
  cannot state a basis the position says which way: `awaiting_valuation` (a market value the
  rates cannot state) or `unvouched` (quantity no lot vouches for), never a partial sum.
- **Grouping**: client-side presentation over the flat portfolio — asset class (family),
  Platform, and Custody Type derived from the Platform kind (self-custody = cold_storage,
  software_wallet; third-party = exchange, broker, bank; now `CONTEXT.md` vocabulary).
- **Cash as its own line**: leg sums include cash; the numéraire values by identity and wears
  no basis (it is the measure), foreign cash and pegged stablecoins value by the latest stored
  reference rate within the publication lookback, its date on display.
- **Markers**: `dangerous`, `ignored`, `unacknowledged` (stance) and `unpriced` (nothing can
  state a value) — visible, explained on hover, excluded from totals, with the exclusions named
  in words above the table.
- **DisplayCurrency**: built here — `lib/display-currency.ts` (localStorage, EUR default) and a
  selector in the page header. Every API figure is EUR; the client multiplies by one served
  reference rate (`/holdings/display-rate/{currency}`), so the choice is structurally unable to
  touch a tax figure. Falls back to EUR, stated, when the rate cannot be served.
- **Access software**: `via {access_software}` on each position's location.
- **Within a second**: no outside I/O on the request path at all — crypto values come from the
  stored last-known price with source and age (ADR-0018), cash from stored rates, and
  `portfolio()` takes no rate source by signature; measured ~40 ms against the seeded dev
  database.

E2E: `apps/web/e2e/holdings.spec.ts` — a cash Opening Balance appears as a located, numéraire-
badged line and regroups by Platform and custody.
