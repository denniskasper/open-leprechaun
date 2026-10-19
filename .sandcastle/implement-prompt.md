# Context

You are working AFK in a sandbox on branch `{{SOURCE_BRANCH}}`, cut from `{{TARGET_BRANCH}}`.
Nobody will answer questions. The host picked one GitHub issue for you; it is below,
with its parent spec when it has one. You have no `gh` and no network access to
GitHub — everything you need from the tracker is here.

{{ISSUE}}

## Recent commits on {{TARGET_BRANCH}}

!`git log --oneline -15 {{TARGET_BRANCH}}`

# Task

Implement issue #{{ISSUE_NUMBER}} — that issue only, not its siblings under the same spec.

1. **Explore** — read `AGENTS.md` and every doc it points to that bears on this change
   (`CONTEXT.md`, relevant ADRs under `docs/adr/`, `docs/agents/design.md` for any UI work).
   Read the source and tests you are about to touch.
2. **Build test-first** — follow the `/tdd` skill at the seams the issue names.
   UI work starts with the `/frontend-design` skill, as `AGENTS.md` requires.
3. **Verify** — all of these must pass before you finish. The database is already up;
   do not run `pnpm test:api`, `pnpm test:e2e` or anything else that calls `docker`.
   - `pnpm lint` (run `pnpm format` first if formatting is off)
   - `apps/api/.venv/bin/python -m pytest -c apps/api/pyproject.toml`
   - `pnpm typecheck`
   - `pnpm test:web`
   - `apps/api/.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head && pnpm --filter @open-leprechaun/web test:e2e`
     (Playwright against the real API and web app; Chromium is installed)
4. **Self-review** — run the `/code-review` skill against `{{TARGET_BRANCH}}`, with
   issue #{{ISSUE_NUMBER}} above as the spec, and fix what it finds.
5. **Commit** — small Conventional Commits, as `AGENTS.md` describes. Reference the
   issue in the body (`Refs #{{ISSUE_NUMBER}}`), not `Closes` — the pull request closes it.

## Rules

- Do not bump versions or edit `CHANGELOG.md`; releases are cut by hand.
- Do not push, and do not touch other branches.
- **No personal financial data** anywhere — code, tests, fixtures, commit messages, or
  the summary below. This repo is public. Use synthetic figures only.
- Do not leave commented-out code or TODOs behind.

# Finish

When the issue is done, committed, and every check passes, end your final message with:

<pr-title>a Conventional Commits subject for the pull request, under ~50 chars</pr-title>
<summary>
Markdown for the pull request body: what changed and why, and any decision a
reviewer should know about. No figures from real accounts. Leave out
`Closes`/`Refs` lines and any "Generated with" attribution — the host adds them.
</summary>
<promise>COMPLETE</promise>

If you cannot finish — the issue is ambiguous, depends on something missing, or a check
fails for a reason you cannot fix — commit nothing half-done. Instead, end with:

<summary>What blocks you, specifically enough that a human can unblock it.</summary>
<promise>BLOCKED</promise>
