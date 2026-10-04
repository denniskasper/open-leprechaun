# Design foundation

The look is a **calibrated instrument**: figures in a fixed-pitch face against
hairline rules, one phosphor-green signal colour used deliberately, generous
whitespace. Two themes carry it — "paper" (light) and "ink" (dark). Restrained
throughout: motion only where it clarifies, colour only where it means
something.

## Tokens

All tokens — colour, type scale, radii, elevation — live in
`apps/web/src/index.css` and nowhere else. Style with the semantic utilities
they generate (`bg-background`, `text-muted-foreground`, `border-border`,
`text-signal`/`text-caution`/`text-alarm`, `shadow-raised`/`shadow-overlay`),
never a raw colour or an arbitrary size. Both themes then follow automatically;
`apps/web/design/contrast.test.ts` re-judges every colour against WCAG AA, so
tune a token and run `pnpm test:web` rather than eyeballing contrast.

The type scale is strict: only the `text-*` sizes defined in the `@theme` block
compile, `text-display` is the one hero size, and `.microlabel` is the small
uppercase fixed-pitch caption over data. UI text is sans (Archivo); data —
figures, codes, timestamps — is `font-mono tabular-nums` (Martian Mono).

## shadcn components

`apps/web/components.json` is configured; add components with
`pnpm dlx shadcn@latest add <name>` from `apps/web/`. They arrive themed
because the tokens use shadcn's variable names. After adding one, delete its
per-component focus-ring classes: the global `:focus-visible` outline in
`index.css` is the one focus treatment, always visible. The one exception is
menu-style items (dropdown items and kin), which follow the platform
convention of an accent-highlight instead — a component may keep
`outline-hidden` only when a `focus:bg-accent` highlight replaces it.

## Shell and navigation

The shell paints the page in `bg-canvas` — a shade darker than the surface,
seen only in the margins — and centres the content sheet on it: `bg-background`
edged by hairline `border-x`. The background is deliberately clean; no screen
adds a texture, gradient or pattern to it.

Pages render into the shell's content region and open with `PageHeader`
(`apps/web/src/components/page-header.tsx`). A new screen registers its route
in `apps/web/src/main.tsx` and its nav entry in `apps/web/src/navigation.ts`;
sidebar, mobile sheet and active states follow from that one entry.

## Settings panels

A screen under Settings is one **panel**. A new one is built from
`apps/web/src/components/patterns/settings-panel.tsx`, never from a bespoke
frame; `apps/web/src/pages/security.tsx` is the reference. Platforms,
Connections, Statutory and Scheduled tasks predate the convention and still
open with `PageHeader` directly — bring one onto it when next reworking it.

- **`SettingsPanel`** — the heading and one line saying what the panel
  governs. It renders the `PageHeader` itself, so a panel does not add its own.
- **`SettingsGroup`** — one named group of controls: title and description on
  the left, controls on the right, stacked on a narrow screen. Groups are
  ruled apart by hairlines; no cards, no boxes.

The description is where a consequence is stated, before the control that
causes it ("ends every Session, this one included") — not in a confirmation
dialog afterwards. A value the panel reports is a fixed-pitch figure with a
`.microlabel` beside it; a control that failed says so in place, with
`ErrorState` or a `role="alert"` line, and one that succeeded with a
`role="status"` line.

An authenticator code is asked for with `CodeField`
(`components/patterns/code-field.tsx`) wherever one is owed — login included —
and a QR code is drawn with `QrCode` (`components/patterns/qr-code.tsx`), whose
plate stays light in both themes because a scanner needs dark on light.

A panel registers in `navigation.ts` under Settings as `/settings/<panel>`.
Settings has no index page: a bare `/settings` redirects to the first panel
declared there (`SETTINGS_INDEX`), so adding a panel is the one entry plus its
route.

## Numbers

Format through `apps/web/src/lib/format.ts`, always. Money goes through
`formatMoney`, which keeps the currency adjacent — a bare number for an amount
of money must not appear on any screen — or `formatMoneyExact` where the
amount is a fixed-point decimal string off the API, or `formatEur` where a
column of EUR tax figures should align to the cent. Quantities use
`formatNumber`, or `formatQuantity` where the value is a fixed-point decimal
string — those must never pass through a float — and `formatSignedQuantity`
where the sign is the point. A share is `formatPercent`, a file size
`formatBytes`. Timestamps use `formatTimestamp` and date-only values
`formatDate`; all format per locale.

## Charts

Charts are inline SVG drawn with the tokens — no chart library and no second
palette; `apps/web/src/pages/portfolio.tsx` is the reference. A series is told
apart by its line (solid ink, dashed muted), never by a new hue; magnitude is
an ink bar on a `bg-muted` track, labelled with its figure, a grouped
remainder in `bg-muted-foreground`; the status tones stay reserved for
readings and never name a series. A line chart has a readout in words and
figures that follows pointer and arrow keys, and a table of the same points.
Every chart says how much of the data it covers. A point that cannot be
stated breaks the line — it never falls to zero.

## Empty and error states

Two reusable patterns in `apps/web/src/components/patterns/`:

- **EmptyState** — the data does not exist yet. Says so in words, names the
  next step, offers it as an action when one exists. Never a blank region.
- **ErrorState** — something failed. Says what failed and offers retry; the
  rest of the screen stays usable. An error never blanks the page.

A screen that can be empty or can fail uses these, not a bespoke treatment.

## Other shared patterns

The same directory holds the rest of what screens share:

- **Lamp** (`lamp.tsx`) — the status dot, with `TONE` as the one pairing of a
  tone (`signal`, `caution`, `alarm`, `idle`) to its text and lamp colour. It
  breathes only while something is live; a settled state stays still.
- **PasswordField** (`password-field.tsx`) — a labelled password input with a
  hint or, in its place, an error. Every form that takes a password uses it.
- **CodeField** and **QrCode** — see Settings panels above.

## Motion

One orchestrated page load: `rise` with staggered inline delays. Beyond that,
motion only where it clarifies a state change. Reduced motion is handled
globally in `index.css`; no component needs its own fallback.
