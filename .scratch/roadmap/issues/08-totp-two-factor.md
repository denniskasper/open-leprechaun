# 08 — TOTP two-factor

**What to build:** The Admin can enable an authenticator-app second factor from settings, and must prove it works before it activates. Login stays a single endpoint.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Enrollment shows a QR code plus the raw URI and secret, and requires a verifying code before activation
- [ ] The secret is encrypted at rest
- [ ] Login returns a distinct `code_required` result when a code is needed, then issues the unchanged token once both factors pass
- [ ] Behaviour is identical on the cookie and bearer paths
- [ ] Enrollment states plainly that there are no recovery codes and that the anti-lockout path is a server-side disable
- [ ] Production shows a persistent reminder while two-factor is off
