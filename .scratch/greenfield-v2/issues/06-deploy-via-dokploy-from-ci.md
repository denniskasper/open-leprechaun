# 06 — Deploy via Dokploy from CI

**What to build:** A green pipeline on the main branch deploys the application; a red one never does. The deployment target sits on a private network with no public address, so the CI runner joins that network for the duration of the deploy job only.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] The platform's own auto-deploy is disabled; CI is the only trigger
- [ ] The deploy job depends on every check job and runs only on the main branch
- [ ] The runner joins the private network as a short-lived node scoped to a CI tag
- [ ] A rejected deployment fails the step visibly, showing what the platform replied
- [ ] Migrations run as a release step, not at application startup
- [ ] Credentials for the platform and the network come from repository secrets, never the workflow file
