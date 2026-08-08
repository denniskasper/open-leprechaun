# 06 — Go live: publish the repository and deploy via Dokploy from CI

**What to build:** This application replaces the one currently running, and from then on a green
pipeline on the main branch deploys it while a red one never does. Two halves: a one-time cutover
that publishes this repository and moves the deployment target off the old application, and the
pipeline body that makes every subsequent deploy automatic. The deployment target sits on a private
network with no public address, so the CI runner joins that network for the duration of the deploy
job only.

**Blocked by:** 05

**Status:** ready-for-human

## Cutover — one-time, performed by a human

The first half cannot be done by an agent: it spans two dashboards and destroys state if done out
of order. Do these in sequence — each step assumes the one above it.

- [ ] The old repository is renamed, so its name is free and its history, issues and stars survive
- [ ] Every local checkout of the old application points at the renamed repository before the name
      is reused — once a new repository takes the old name, GitHub severs the redirect silently
- [ ] The old repository is archived, so it reads as retired rather than merely quiet
- [ ] This repository is published under the freed name and pushed
- [ ] The old application's data is backed up, and the application is stopped rather than deleted,
      so a rollback is still possible
- [ ] A new Dokploy application points at this repository
- [ ] The domain moves to the new application only after it serves traffic correctly
- [ ] The old application is deleted and its volumes reclaimed only once the new one has held
      production for long enough to trust it

## Pipeline — code

- [ ] The platform's own auto-deploy is disabled; CI is the only trigger
- [ ] The deploy job depends on every check job and runs only on the main branch
- [ ] The runner joins the private network as a short-lived node scoped to a CI tag
- [ ] A rejected deployment fails the step visibly, showing what the platform replied
- [ ] Migrations run as a release step, not at application startup
- [ ] Credentials for the platform and the network come from repository secrets, never the workflow
      file
- [ ] A superseding push to main never kills a deployment mid-flight — either main's concurrency
      group stops cancelling in progress, or the deploy gets a group of its own

## Comments

Scope widened from "wire the deploy job" to "go live", because the original criteria could not be
started: every one of them needs a GitHub remote for repository secrets and workflow triggers, and
this repository has never had one. Ticket 05 anticipated this — its pipeline is implemented but
unvalidated, and its comment records that the first push to a remote is the real proof. So the
publication is not parallel work to this ticket; it is what unblocks it. Retiring the old
application belongs here for the same reason: it is the same event, not a follow-up. The moment the
domain moves, the old application must be down.

The status is `ready-for-human` rather than `ready-for-agent` because of the cutover half. The
pipeline half stays agent-shaped once the repository is published, and an agent could pick it up
then.

The final concurrency criterion is ticket 05's explicit handoff: `cancel-in-progress` is currently
unconditional, which was harmless while the deploy job body was a placeholder echo and is not once
it deploys.

Both git hooks (`commit-msg`, `pre-push`) are present in this clone, so the guard against personal
financial data is live before the first push — worth re-checking rather than assuming, since
`AGENTS.md` notes they do not survive a fresh clone. Both repositories are public, so that guard
matters from the first push onward.
