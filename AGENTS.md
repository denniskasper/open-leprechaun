# AGENTS.md

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `<type>(<optional scope>): <description>`.

Keep them short — a subject line under ~50 characters, lowercase, imperative mood, no trailing period. Omit the body unless the _why_ is genuinely non-obvious.

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

```
feat(auth): add session refresh
fix: handle empty payload
docs: note commit conventions
```

## Design and UI

Any work on design or UI — new components, layout, styling, visual polish —
starts by invoking the `/frontend-design` skill. This holds for every session,
without being asked.

## Agent skills

### Issue tracker

Issues live as markdown files under `.scratch/<feature>/` in this repo — there is no hosted tracker. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name, recorded as a `Status:` line in the issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Git

- **Never force-push.** Do not run `git push --force`, `-f`, or `--force-with-lease` on any branch. If a force-push ever seems necessary, stop and ask first.
- **No personal financial data in anything pushed.** This repo is public. Commit messages, the changelog, PR/issue text, code, and tests must never contain account-derived numbers (P&L, losses, balances, position or trade counts, coins held). Describe changes technically; statutory constants from tax law are fine. Local git hooks (`.git/hooks/commit-msg`, `.git/hooks/pre-push`) enforce this — recreate them after a fresh clone.
