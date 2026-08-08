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

Pages render into the shell's content region and open with `PageHeader`
(`apps/web/src/components/page-header.tsx`). A new screen registers its route
in `apps/web/src/main.tsx` and its nav entry in `apps/web/src/navigation.ts`;
sidebar, mobile sheet and active states follow from that one entry.

## Numbers

Format through `apps/web/src/lib/format.ts`, always. Money goes through
`formatMoney`, which keeps the currency adjacent — a bare number for an amount
of money must not appear on any screen. Quantities use `formatNumber`,
timestamps `formatTimestamp`; all three format per locale.

## Empty and error states

Two reusable patterns in `apps/web/src/components/patterns/`:

- **EmptyState** — the data does not exist yet. Says so in words, names the
  next step, offers it as an action when one exists. Never a blank region.
- **ErrorState** — something failed. Says what failed and offers retry; the
  rest of the screen stays usable. An error never blanks the page.

A screen that can be empty or can fail uses these, not a bespoke treatment.

## Motion

One orchestrated page load: `rise` with staggered inline delays. Beyond that,
motion only where it clarifies a state change. Reduced motion is handled
globally in `index.css`; no component needs its own fallback.
