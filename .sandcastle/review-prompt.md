# Context

You are reviewing AFK, in a sandbox, the work another agent just committed on branch
`{{SOURCE_BRANCH}}` for this issue. Nobody will answer questions, and you have no
access to GitHub — the issue is below.

{{ISSUE}}

## Commits on this branch

!`git log --oneline {{TARGET_BRANCH}}..HEAD`

## Diff

!`git diff --stat {{TARGET_BRANCH}}...HEAD`

# Task

Run the `/code-review` skill with `{{TARGET_BRANCH}}` as the fixed point and issue
#{{ISSUE_NUMBER}} above as the spec. Then act on what it finds:

- **Spec gaps and bugs** — fix them.
- **Standards findings** — fix the ones `AGENTS.md` and the docs it points to actually
  require; leave pure taste alone.
- Preserve behaviour the issue asked for. Do not widen the scope.

If you changed anything, re-run every check and keep them green:

- `pnpm lint`
- `apps/api/.venv/bin/python -m pytest -c apps/api/pyproject.toml`
- `pnpm typecheck`
- `pnpm test:web`

Commit fixes as Conventional Commits. Do not push, bump versions, or edit
`CHANGELOG.md`. No personal financial data anywhere — this repo is public.

# Finish

End your final message with a short review for the pull request body — what you
checked, what you fixed, and anything a human should still look at:

<review>
Markdown, a few bullets.
</review>
<promise>COMPLETE</promise>
