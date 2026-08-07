# 05 — CI pipeline, decomposed

**What to build:** Every push runs the checks, and the pipeline is split so that a change to one concern does not require reading another. An orchestrating workflow calls one reusable workflow per concern; toolchain setup is defined once as composite actions.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] An orchestrating workflow calls reusable workflows for API checks, web checks and end-to-end tests
- [ ] Toolchain setup for each side exists once as a composite action, not repeated per job
- [ ] Runs are concurrency-grouped so a superseding push cancels the run it overtook
- [ ] A branch with an open pull request does not run twice
- [ ] Migrations are tested up and down as part of the API checks
- [ ] All checks must pass before any deploy job becomes eligible
