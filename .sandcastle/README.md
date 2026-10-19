# Sandcastle — AFK agents

[Sandcastle](https://github.com/mattpocock/sandcastle) works the `ready-for-agent`
backlog unattended: one issue at a time, implemented and reviewed by Claude in a
Docker sandbox, landed as a pull request that closes the issue.

## One-time setup

```bash
pnpm install
cp .sandcastle/.env.example .sandcastle/.env    # then paste the token:
claude setup-token                              # → CLAUDE_CODE_OAUTH_TOKEN
npx sandcastle docker build-image               # again after editing the Dockerfile
```

## Run

From a clean checkout of the branch the PRs should target (usually `main`):

```bash
pnpm sandcastle        # up to MAX_ISSUES issues, oldest first
pnpm sandcastle 17     # just #17
```

Logs stream to `.sandcastle/logs/`. A run of two agents plus the full test suite
takes a while per issue — leave it.

## What happens

- **Pick** — open `ready-for-agent`, not `spec`, no open blocker, no open PR from
  `sandcastle/issue-<n>`.
- **Implement, review, check** — lint, API and web tests, typecheck and the Playwright
  e2e suite, inside the sandbox, against a Postgres database of its own
  (`leprechaun_sandcastle`) on the Compose container.
- **Land** — the host pushes and opens the PR; a draft if a check failed. An agent
  that gets stuck comments on the issue and moves it to `needs-triage`.

The sandbox holds no GitHub credentials. Pushes, PRs and issue comments go
through your own `gh` login and git hooks, and agent-written PR and comment text
is run through `.git/hooks/commit-msg` first. Nothing reaches `main` until you
merge.

Models, effort, `MAX_ISSUES` and the checks sit at the top of `main.mts`.
