# TOTP two-factor authentication for the admin login, with no recovery codes

## Status

accepted — carried from v1's ADR-0005

## Context

Before real financial data sits on an internet-facing server, a leaked or reused password must not
by itself grant access. The application is single-admin and self-hosted: there is no user
directory, no mail infrastructure, and the Admin always has shell access to the host.

## Decision

Optional TOTP as a second factor, enabled from settings with a verify-before-activate step and
enforced wherever authentication is active. The secret is encrypted at rest by the same mechanism
as venue credentials. Login stays a single endpoint: it returns a distinct "code required" result,
and a correct code gates issuance of the unchanged token rather than changing it. Enrollment shows
the QR code alongside the raw URI and secret, so an Admin who keeps secrets in a password store
need not photograph a screen.

**No recovery codes.** The only anti-lockout path is a targeted server-side disable, and the UI
says so at enrollment.

## Considered Options

- **Recovery codes.** Rejected: the device-loss lockout that justifies them elsewhere does not
  apply to someone who controls the host and keeps the secret in a backed-up password store. A
  future multi-user or hosted deployment must revisit this.
- **WebAuthn or passkeys.** Rejected: single-admin recovery is painful, and it is a different
  device class from the Admin's existing workflow.
- **Emailed one-time codes.** Rejected: no mail infrastructure, and email often shares the
  password's threat surface.

## Consequences

- Losing the authenticator device does not lock the Admin out while the secret remains in their
  password store; total loss is recoverable only with host access.
- Production shows a persistent reminder while two-factor is off.
