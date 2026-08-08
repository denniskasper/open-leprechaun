# 05 — CI pipeline, decomposed

**What to build:** Every push runs the checks, and the pipeline is split so that a change to one concern does not require reading another. An orchestrating workflow calls one reusable workflow per concern; toolchain setup is defined once as composite actions.

**Blocked by:** 01

**Status:** ready-for-agent

- [x] An orchestrating workflow calls reusable workflows for API checks, web checks and end-to-end tests
- [x] Toolchain setup for each side exists once as a composite action, not repeated per job
- [x] Runs are concurrency-grouped so a superseding push cancels the run it overtook
- [x] A branch with an open pull request does not run twice
- [x] Migrations are tested up and down as part of the API checks
- [x] All checks must pass before any deploy job becomes eligible

## Comments

Implemented. `.github/workflows/ci.yml` orchestrates; `api-checks.yml`, `web-checks.yml`,
`e2e.yml` and `deploy.yml` are `workflow_call` workflows, one per concern (deploy's body is a
placeholder for ticket 06 — the spec names deploy as a concern, so the shape exists now);
`.github/actions/setup-api` and `.github/actions/setup-web` define each side's toolchain once. Every job runs the same root pnpm
scripts a developer runs — Postgres comes from the same Compose file via `pnpm db:up` inside
`test:api`/`test:e2e`, not from a CI-only `services:` block.

How each criterion is held:

- **No double runs for a PR branch**: `push` covers every branch in this repository, so a
  same-repo pull request shows the push run on its head and nothing else. `pull_request` exists
  solely for forks — whose pushes cannot trigger workflows here — and a job-level guard skips it
  for same-repo branches. Every push runs the checks; nothing runs twice.
- **Cancellation** is `concurrency: ci-${{ github.ref }}` with `cancel-in-progress: true`,
  per-ref so branches never cancel each other.
- **Migrations up and down** ride on `pnpm test:api`: ticket 03's chain-walk test
  (`base ⇄ head ⇄ base ⇄ head`) runs inside pytest, exactly as that ticket anticipated.
- **The deploy gate** is the `deploy` job with `needs: [api, web, e2e]`, restricted to main. Its
  body is a placeholder echo; ticket 06 replaces the body — the `needs` list is the part that
  must survive.

Deviations and decisions worth recording:

- **The pipeline cannot run yet.** This repo has no git remote (`docs/agents/issue-tracker.md`
  records that), so validation is local: actionlint 1.7.12 is clean over the workflows, the
  composite actions parse, and every command each job runs (`pnpm lint`, `typecheck`, `test`,
  `build`, `test:e2e`) passed locally. First push to a GitHub remote is the real proof.
- **Both composite actions install pnpm and Node**, because the root pnpm scripts are the single
  entry point on both sides. The e2e job therefore runs `pnpm/action-setup` twice; that is safe —
  its installer wipes its destination and reinstalls (verified in the v6 source).
- **The e2e job migrates before testing** (`pnpm db:migrate`), so end-to-end tests see the state
  a deployed instance is in — migrations being a release step. Local `pnpm test:e2e` does not
  migrate; if e2e ever needs schema locally, that is the script to revisit.
- **Handoff to ticket 06:** `cancel-in-progress` is unconditional, so a superseding push to main
  cancels an in-flight main run. Fine while the deploy job is an echo; once it deploys, ticket 06
  should decide whether main's group needs `cancel-in-progress: false` or a deploy-scoped
  concurrency group so a deployment is never killed mid-flight.
- **Action pins are major tags** (`checkout@v7`, `setup-node@v7`, `setup-python@v7`,
  `upload-artifact@v7`, `pnpm/action-setup@v6`), current as of this writing. The pnpm version
  itself is not pinned in the workflow — `pnpm/action-setup` reads `packageManager` from
  package.json, so the pin lives in one place.
- **No paths filters and no Playwright browser cache.** Every push runs everything; with one
  browser and a small suite, the simplicity is worth more than the minutes.

Post-review fixes: deploy became its own reusable workflow (the spec lists deploy among the
per-concern workflows, so ticket 06 fills a body rather than restructuring); a guarded
`pull_request` trigger gives fork pull requests checks without double-running same-repo
branches; and the environment-file step moved into `setup-api`, where both jobs that talk to
Compose already were.
