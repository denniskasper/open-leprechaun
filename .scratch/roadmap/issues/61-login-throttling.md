# 61 — Login throttling

**What to build:** A brute-force cost on the login endpoint that never locks the Admin out. One password guards a self-hosted server reachable from the internet, and today an attacker may guess at full speed.

**Blocked by:** 07

**Status:** done

- [x] Failed login attempts are counted per source address and delay subsequent attempts, backing off exponentially to a capped maximum
- [x] A correct password clears that address's failures
- [x] The account is never locked — no sequence of failures can leave the Admin unable to log in with the right password
- [x] Failures are counted in the database, so a restart is not a free reset and every worker shares one count
- [x] A throttled attempt is refused without revealing whether the password was right
- [x] Old failure records are purged alongside expired sessions
- [x] Covered by a test that a throttled address is delayed and one that the correct password still succeeds after the backoff

## Notes

**The trap this avoids.** With one Admin and no recovery codes (ADR 0005), any rule that locks the
account hands an attacker a denial of service: hammer the login and the owner is shut out of their
own financial history with no path back except host access. Backoff makes guessing uneconomical
without ever creating a state the Admin cannot leave.

Per-address rather than global for the same reason — a global counter on a self-hosted box behind
one household address is a lock the Admin trips themselves.

The decision is recorded in `docs/adr/0015-login-throttling-backs-off-per-address.md`.

## Comments

Implemented as a `login_failure` row per source address holding a count and the instant the
address may next attempt. One second after the first failure, doubling per failure, capped at five
minutes; a record goes stale a day after its delay ran out. A throttled attempt answers 429 with
`Retry-After`, before the password is verified.

The attempt is counted *before* the password is checked, in the single upsert that decides whether
to admit it, and a correct password then deletes the row. That makes the row the arbiter between
workers: a burst of simultaneous guesses gets one through, not all of them. Throttled attempts
neither count nor extend the delay, so hammering cannot push the Admin's next chance further away.

The purge runs where the session purge already ran — on a successful login. The stale rule is also
applied inside the upsert, so behaviour does not depend on when the purge last ran.

**Carried to ticket 06.** The source address is the peer uvicorn reports. Behind Dokploy's proxy
that is the real client only if uvicorn is started trusting the proxy's forwarded headers;
otherwise every caller shares the proxy's address and the count is in effect global — the option
ADR 0015 rejects. The start command does not exist yet, so the requirement is recorded there.
