# 59 — Clean background

**What to build:** Strip the textured background from the shell. The bench-surface
treatment from ticket 02 — measuring grid, lamp glow, grain pass — reads as busy;
the background should be clean. Reference: https://www.aihero.dev/skills, whose
calm comes from a dead-flat page background with a slightly lighter content sheet
framed by hairline left/right borders — no texture at all.

**Blocked by:** 02

**Status:** ready-for-agent

- [x] Remove the grid, glow and grain from the app background in both themes
- [x] Content reads as a clean sheet on a slightly darker canvas, edged by hairline borders
- [x] Both themes still pass the WCAG AA contrast suite
- [x] `docs/agents/design.md` updated so later tickets inherit the clean background

## Comments

Implemented. The `.instrument-field` component class (grid + radial glow + SVG
grain) is deleted from `index.css`, along with its tokens (`--etch`,
`--surface-glow`, `--grain-blend`, `--grain-opacity`).

In its place, the aihero structure in the existing paper/ink palette:

- A new `--canvas` token per theme — a shade darker than `--background`
  (paper: `oklch(0.945 0.006 95)`, ink: `oklch(0.125 0.01 155)`) — mapped as
  `bg-canvas`. It appears only in the shell's margins; no text renders on it,
  so no new contrast pairs were needed.
- The shell root paints `bg-canvas`; the centred `max-w-6xl` container becomes
  the content sheet: `bg-background border-x border-border`.
- The auth screen drops the texture and sits full-bleed on `bg-background`.
- `docs/agents/design.md` § Shell now records the canvas/sheet structure and
  that no screen adds a texture, gradient or pattern to the background.

Verified: all 75 web tests pass (including `design/contrast.test.ts` in both
themes), and both themes were screenshotted against the running stack — flat
surfaces, hairline sheet edges, no pattern.
