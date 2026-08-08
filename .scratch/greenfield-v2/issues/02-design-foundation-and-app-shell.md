# 02 — Design foundation and app shell

**What to build:** The visual language every later screen inherits, proven by building one real screen in it — the application shell with navigation, plus the health view from ticket 01 rendered properly. Modern and restrained, taking its cues from Apple's and Google's product surfaces: generous whitespace, a strict type scale, few colours used deliberately, motion only where it clarifies.

Establish this once so no later ticket invents its own look.

**Blocked by:** 01

**Status:** ready-for-agent

- [x] Begin by invoking the `/frontend-design` skill, per AGENTS.md
- [x] Design tokens — type scale, spacing, radii, elevation, colour — defined once and consumed by components
- [x] Light and dark themes both meet WCAG AA contrast
- [x] shadcn components themed to the tokens rather than used at their defaults
- [x] An application shell with navigation, page header and content region
- [x] Keyboard navigable throughout with a visible focus state
- [x] Numbers formatted per locale with the currency always adjacent — never a bare number
- [x] A documented empty-state and error-state pattern that later tickets reuse

## Comments

Implemented. The walking skeleton's instrument aesthetic was kept and matured into a two-theme
token system rather than replaced. Everything below is documented for later tickets in
`docs/agents/design.md`, pointed at from `AGENTS.md`.

- **Tokens** live once in `apps/web/src/index.css` under shadcn's semantic variable names
  (`--background`, `--primary`, …) mapped per theme — "paper" (light) and "ink" (dark) — plus the
  status tones `signal`/`caution`/`alarm`. Any component the shadcn CLI adds later arrives themed.
- **WCAG AA is a test, not a claim.** `apps/web/design/contrast.test.ts` parses the token blocks
  and judges the text and indicator pairs the UI renders, in both themes, with culori — the test
  enforces 4.5:1 (text) and 3:1 (indicators); the values as committed clear the text bar with room
  to spare.
- **The type scale is enforced**: Tailwind's default sizes are cleared, so a `text-*` size outside
  the scale does not compile.
- **shadcn is hand-vendored, not CLI-generated** (`button`, `dropdown-menu`, `separator`, `sheet`),
  in the CLI's shape but bound to the tokens — per-component focus rings removed in favour of one
  global always-visible `:focus-visible` outline. `components.json` is configured so later tickets
  can `pnpm dlx shadcn@latest add`.
- **Shell**: sidebar navigation (mobile: sheet), header, content region, with a skip link as the
  first tab stop. Routing via react-router; nav entries are declared once in `src/navigation.ts`.
  The health view from ticket 01 is re-rendered inside the shell as its proving screen.
- **Theme preference** (light/dark/system) persists in localStorage, applied by an inline script
  in `index.html` before first paint so no flash, tracked live when following the OS.
- **Formatting** through `src/lib/format.ts` (built test-first): `formatMoney` keeps the currency
  adjacent so money cannot render bare; `formatNumber` and `formatTimestamp` cover quantities and
  times per locale.
- **Empty/error patterns** are components in `src/components/patterns/` with usage rules in the
  design doc; the health page's unreachable case uses `ErrorState` as the first real example.
- **Verified** by the vitest suites (formatting, contrast) and Playwright journeys (health readout,
  skip link + keyboard path, nav aria-current, theme toggle + persistence across reload), and by
  driving the running stack in a browser in both themes.

Deviations worth recording:

- **react-router is a new runtime dependency** not named in the spec's stack line. "An application
  shell with navigation" needs routes for later tickets to register against; declaring navigation
  once in `src/navigation.ts` and letting the router mark the active page follows from that.
- **A theme toggle (light/dark/system) shipped**, though the ticket only demands AA in both themes.
  Without a switcher the light theme would be unreachable for anyone whose OS reports dark, so it
  is treated as part of proving the second theme rather than as new scope.
- **Money is proven in the library, not on a screen** — no screen renders an amount of money yet.
  `formatMoney` is the only way to render one and its adjacency rule is unit-tested; the first
  money-bearing screen exercises it for real.
