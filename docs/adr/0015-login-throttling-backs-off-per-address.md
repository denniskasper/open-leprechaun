# Login throttling backs off per address and never locks the Admin out

## Status

accepted

## Context

The login endpoint guards a self-hosted server holding one person's complete financial history,
and a single password opens it. Unthrottled, it can be guessed at network speed. The obvious
countermeasure — lock the account after N failures — is unusually dangerous here: the application
is single-admin by construction (ADR 0006) and two-factor deliberately ships without recovery
codes (ADR 0005), so a lockout has no self-service exit.

## Decision

Failed attempts are counted per source address and delay the next attempt, backing off
exponentially to a cap. A correct password clears that address's failures. **The account is never
locked**, whatever the failure count. Counts live in the database so a restart does not reset them
and every worker shares one view.

## Considered Options

- **Lock the account after N failures.** Rejected: it converts a brute-force attempt into a
  guaranteed denial of service against the only Admin, whose sole recovery path would be shell
  access to the host.
- **A global counter rather than per-address.** Rejected: a self-hosted instance is reached from
  a handful of addresses, so a global count is a lock the Admin trips themselves.
- **In-memory counters.** Rejected: a restart becomes a free reset, and separate workers would
  each keep their own count.

## Consequences

- An attacker with many source addresses is slowed per address rather than absolutely; the
  password minimum and two-factor remain the defences that do not depend on origin.
- Throttling is stateful, so login now writes on the failure path — the purge that removes
  expired sessions removes stale failure records too.
