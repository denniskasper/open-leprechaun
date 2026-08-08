# 08 — TOTP two-factor

**What to build:** The Admin can enable an authenticator-app second factor from settings, and must prove it works before it activates. Login stays a single endpoint.

**Blocked by:** 07, 60

**Status:** ready-for-agent

- [ ] Enrollment shows a QR code plus the raw URI and secret, and requires a verifying code before activation
- [ ] The secret is encrypted at rest
- [ ] Login returns a distinct `code_required` result when a code is needed, then issues the unchanged token once both factors pass
- [ ] Behaviour is identical on the cookie and bearer paths
- [ ] Enrollment states plainly that there are no recovery codes and that the anti-lockout path is a server-side disable
- [ ] The server-side disable is a real, documented command with a runbook entry — the enrollment copy promises it, so it must exist and be findable under pressure
- [ ] Changing the password requires a current code while two-factor is active; `POST /api/auth/password` (ticket 60) gains an optional `code` field
- [ ] Enrollment and disable live in the Security panel built by ticket 60, following its panel convention
- [ ] Production shows a persistent reminder while two-factor is off
