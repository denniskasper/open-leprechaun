# 61 — Login throttling

**What to build:** A brute-force cost on the login endpoint that never locks the Admin out. One password guards a self-hosted server reachable from the internet, and today an attacker may guess at full speed.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Failed login attempts are counted per source address and delay subsequent attempts, backing off exponentially to a capped maximum
- [ ] A correct password clears that address's failures
- [ ] The account is never locked — no sequence of failures can leave the Admin unable to log in with the right password
- [ ] Failures are counted in the database, so a restart is not a free reset and every worker shares one count
- [ ] A throttled attempt is refused without revealing whether the password was right
- [ ] Old failure records are purged alongside expired sessions
- [ ] Covered by a test that a throttled address is delayed and one that the correct password still succeeds after the backoff

## Notes

**The trap this avoids.** With one Admin and no recovery codes (ADR 0005), any rule that locks the
account hands an attacker a denial of service: hammer the login and the owner is shut out of their
own financial history with no path back except host access. Backoff makes guessing uneconomical
without ever creating a state the Admin cannot leave.

Per-address rather than global for the same reason — a global counter on a self-hosted box behind
one household address is a lock the Admin trips themselves.

The decision is recorded in `docs/adr/0015-login-throttling-backs-off-per-address.md`.
