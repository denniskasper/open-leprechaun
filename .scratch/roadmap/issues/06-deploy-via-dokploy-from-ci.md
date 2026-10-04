# 06 — Go live: publish the repository and deploy via Dokploy from CI

**What to build:** This application replaces the one currently running, and from then on a green
pipeline on the main branch deploys it while a red one never does. Two halves: a one-time cutover
that publishes this repository and moves the deployment target off the old application, and the
pipeline body that makes every subsequent deploy automatic. The deployment target sits on a private
network with no public address, so the CI runner joins that network for the duration of the deploy
job only.

**Blocked by:** 05

**Status:** done

## Cutover — one-time, performed by a human

The first half cannot be done by an agent: it spans two dashboards and destroys state if done out
of order. Do these in sequence — each step assumes the one above it.

- [x] The old repository is renamed, so its name is free and its history, issues and stars survive
- [x] Every local checkout of the old application points at the renamed repository before the name
      is reused — once a new repository takes the old name, GitHub severs the redirect silently
- [x] The old repository is archived, so it reads as retired rather than merely quiet
- [x] This repository is published under the freed name and pushed
- [x] The old application's data is backed up, and the application is stopped rather than deleted,
      so a rollback is still possible
- [x] A new Dokploy application points at this repository
- [x] The domain moves to the new application only after it serves traffic correctly
- [x] The old application is deleted and its volumes reclaimed only once the new one has held
      production for long enough to trust it

## Pipeline — code

- [x] The platform's own auto-deploy is disabled; CI is the only trigger
- [x] The deploy job depends on every check job and runs only on the main branch
- [x] The runner joins the private network as a short-lived node scoped to a CI tag
- [x] A rejected deployment fails the step visibly, showing what the platform replied
- [x] Migrations run as a release step, not at application startup
- [x] Credentials for the platform and the network come from repository secrets, never the workflow
      file
- [x] A superseding push to main never kills a deployment mid-flight — either main's concurrency
      group stops cancelling in progress, or the deploy gets a group of its own
- [x] The API is started trusting the proxy's forwarded headers and nothing else's
      (`--proxy-headers --forwarded-allow-ips <the proxy>`), so login throttling (ticket 61) counts
      failures per real client address rather than against the proxy's one address

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

**Update (2026-10-04).** The statement above that this repository has never had a remote is out of date:
`origin` exists and main is pushed to it, so repository secrets and workflow triggers are no longer
blocked on publication. Which cutover steps that completes is for whoever performed them to tick —
none is ticked here on inference. Ticket 08 added two things this ticket inherits: the
proxy-header criterion now also protects password change and the two-factor disable, which share
login's per-address count; and `docs/runbook.md`'s two-factor entry gives a generic
`docker exec` example that should become the real command once the container shape exists.

**Update (2026-10-04).** The pipeline half is written: a `Dockerfile` with an `api` and a `web`
image, `deploy/compose.tailnet.yaml`, the deploy and not-public scripts, the body of
`.github/workflows/deploy.yml`, and `docs/deployment.md` for what is set up by hand. Ticked above
is what the code does; none of it has run against Dokploy yet, so the first deployment is the proof.
The stack was started locally with a stand-in for the Tailscale sidecar: migrations ran before the
API, the client and deep links were served, and a forwarded address from loopback reached the API's
log as the client. The auto-deploy criterion stays unticked — it is a switch in Dokploy.

Two things differ from the ticket as written. The instance is served over the tailnet only, by a
Tailscale sidecar under a MagicDNS name, so there is no domain to move and no Traefik router; the
"domain moves" cutover step has nothing to act on. And the forwarded-header criterion is met with
loopback as the one trusted address, because the API, the web server and the sidecar share a
network namespace.

Observed, for whoever ticks the cutover: on GitHub the old repository is `open-leprechaun-legacy`,
private and archived, and this one is published as `open-leprechaun`; the Dokploy host runs no old
application. Not observed: a backup of the old application's data. The deploy job is skipped until
the `DOKPLOY_COMPOSE_ID` repository variable is set.

**Update (2026-10-04), later.** Live. The Dokploy compose service exists with auto-deploy off, the
first deployment ran from the pipeline, and its not-public job found every door shut. The instance
answers over the tailnet, migrations ran before the API started, and the API logs the caller's
tailnet address rather than the proxy's.

The cutover boxes are ticked on this basis: the old repository is renamed and archived and this one
published; the one local checkout of the old application was removed rather than repointed, after
its data was kept outside the repository; the Dokploy host ran no old application to stop or
delete; and the domain step has nothing to act on, as noted above. Left for later, outside this
ticket: a scheduled database backup (`docs/deployment.md` § Backing up).
