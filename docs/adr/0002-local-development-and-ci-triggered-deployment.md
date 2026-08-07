# Local-first development; deployment triggered by CI over a private network

## Status

accepted — supersedes v1's ADR-0001

## Context

v1 ran a Makefile over Docker Compose for local work and deployed separately. The Makefile was
overhead for two services, and the deployment target is now a platform that builds and runs
containers itself, reachable only inside a private network.

## Decision

Locally, dependencies are installed on the host so a debugger attaches and the IDE resolves
imports; only Postgres runs in Docker. There is no Makefile — package-manager scripts at the
repository root are the single documented entry point, and they invoke the backend's tooling too.

Deployment is the container platform on a VPS. Its own auto-deploy is **off**; the pipeline
triggers a deploy through the platform's API only after every check has passed. Because the
platform has no public address, the CI runner joins the private network as a short-lived node for
the duration of that job. Migrations run as a release step, never at application startup.

## Considered Options

- **Let the platform deploy on push.** Rejected: checks and deployment then race, and a red run
  reaches production anyway.
- **Expose the platform publicly and call it directly.** Rejected: it is an administrative
  surface for the whole host.
- **Keep a Makefile, or adopt a task runner.** Rejected as a second build system to learn for a
  two-service repository.

## Consequences

- The pipeline holds credentials for both the private network and the platform; they live as
  repository secrets and never in a workflow file.
- A deployment cannot happen from a developer's machine by accident — the pipeline is the only
  path.
