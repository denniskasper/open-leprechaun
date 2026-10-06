# Design foundation

The look is a **calibrated instrument**: figures in a fixed-pitch face against
hairline rules, one phosphor-green signal colour used deliberately, generous
whitespace. Two themes carry it — "paper" (light) and "ink" (dark). Restrained
throughout: motion only where it clarifies, colour only where it means
something.

## Tokens

All tokens — colour, type scale, radii, elevation — live in
`apps/web/src/index.css` and nowhere else (the favicon and the `theme-color`
meta are the one exception, see below). Style with the semantic utilities they
generate (`bg-background`, `text-muted-foreground`, `border-border`,
`text-signal`/`text-caution`/`text-alarm`, `shadow-raised`/`shadow-overlay`),
never a raw colour or an arbitrary size. Both themes then follow automatically;
`apps/web/design/contrast.test.ts` re-judges every colour against WCAG AA, so
tune a token and run `pnpm test:web` rather than eyeballing contrast.

The type scale is strict: only the `text-*` sizes defined in the `@theme` block
compile, `text-display` is the one hero size, and `.microlabel` is the small
uppercase fixed-pitch caption over data. UI text is sans (Archivo); data —
figures, codes, timestamps — is `font-mono tabular-nums` (Martian Mono).

## Favicon and browser chrome

The tab icon is the shell's clover on a tile of its own — the ink theme's
`--primary` on the ink theme's `--background`, the same on every tab strip
whatever the OS or the theme toggle says. The drawing is
`apps/web/public/favicon.svg`; `favicon.ico` and `apple-touch-icon.png` beside
it are rendered from it and committed. After changing the drawing, run
`node design/render-favicon.ts` from `apps/web/` and commit what it writes.

The `theme-color` meta in `apps/web/index.html` carries each theme's
`--background`, and follows the theme toggle rather than the OS.

These are the one exception to colours living in `index.css`, because
browser chrome reads no CSS variable. `apps/web/design/favicon.test.ts` holds
each literal to its token: tune the token, and the test names what to update.

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
where the sign is the point. An amount of an asset that is no ISO currency — a
coin, a stablecoin — keeps its symbol adjacent the same way, through
`formatAssetAmount` or `formatSignedAssetAmount`. A price is the one figure
that may stand bare, and only where its source names no currency for it: a
venue's mark or fill price is repeated as stated, never given a currency the
venue did not say. A share is `formatPercent`, or `formatPercentExact` and
`formatSignedPercentExact` where it arrives as a fixed-point string; a file
size is `formatBytes`. Timestamps use `formatTimestamp` and date-only values
`formatDate`; all format per locale.

The formatters above state digits verbatim. A list or a table rounds what it
shows instead, with the digits as stated one hover away: use the components in
`components/patterns/figure.tsx` — `Amount`, `Money`, `Price` — which pair the
rounded figure with the verbatim one as its `title`; in a sentence or an
`aria-label`, the `formatRounded*` functions, `formatMoneyRounded` and
`formatPrice`. Money and stablecoins read to the cent — whole amounts without
a fraction, a currency-styled value always padded — a coin to eight places, a
price to two decimals at one or above and four significant digits below.
Rounding is half away from zero, on the digits, and an amount that is not zero
never reads as zero: it widens to its first significant digit instead. Which
symbols read as money is a short list in `format.ts`; where a screen knows the
Instrument is a security, it passes no symbol.

These state the digits verbatim and are never rounded: a form's fields and an
import's preview, where the input itself is being checked; a Reconciliation's
figures and differences, and any sentence whose point is a difference; EUR tax
figures; and a rate or ratio — an exchange rate, a leverage, a split.

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
- **Amount**, **Money** and **Price** (`figure.tsx`) — a figure rounded for
  reading, its digits as stated on hover. See Numbers above.
- **CodeField** and **QrCode** — see Settings panels above.

## Motion

One orchestrated page load: `rise` with staggered inline delays. Beyond that,
motion only where it clarifies a state change. Reduced motion is handled
globally in `index.css`; no component needs its own fallback.
