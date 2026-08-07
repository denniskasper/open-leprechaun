# 02 — Design foundation and app shell

**What to build:** The visual language every later screen inherits, proven by building one real screen in it — the application shell with navigation, plus the health view from ticket 01 rendered properly. Modern and restrained, taking its cues from Apple's and Google's product surfaces: generous whitespace, a strict type scale, few colours used deliberately, motion only where it clarifies.

Establish this once so no later ticket invents its own look.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Begin by invoking the `/frontend-design` skill, per AGENTS.md
- [ ] Design tokens — type scale, spacing, radii, elevation, colour — defined once and consumed by components
- [ ] Light and dark themes both meet WCAG AA contrast
- [ ] shadcn components themed to the tokens rather than used at their defaults
- [ ] An application shell with navigation, page header and content region
- [ ] Keyboard navigable throughout with a visible focus state
- [ ] Numbers formatted per locale with the currency always adjacent — never a bare number
- [ ] A documented empty-state and error-state pattern that later tickets reuse
