# 08 — TOTP two-factor

**What to build:** The Admin can enable an authenticator-app second factor from settings, and must prove it works before it activates. Login stays a single endpoint.

**Blocked by:** 07, 60

**Status:** done

- [x] Enrollment shows a QR code plus the raw URI and secret, and requires a verifying code before activation
- [x] The secret is encrypted at rest
- [x] Login returns a distinct `code_required` result when a code is needed, then issues the unchanged token once both factors pass
- [x] Behaviour is identical on the cookie and bearer paths
- [x] Enrollment states plainly that there are no recovery codes and that the anti-lockout path is a server-side disable
- [x] The server-side disable is a real, documented command with a runbook entry — the enrollment copy promises it, so it must exist and be findable under pressure
- [x] Changing the password requires a current code while two-factor is active; `POST /api/auth/password` (ticket 60) gains an optional `code` field
- [x] Enrollment and disable live in the Security panel built by ticket 60, following its panel convention
- [x] Production shows a persistent reminder while two-factor is off

## Comments

Implemented (2026-10-04). RFC 6238 against the standard library — SHA-1, six digits,
thirty-second steps, one step of drift either side — so no new dependency carries the credential
path. Three nullable columns on `admin_user`: the active secret, a pending one, and the step of the
last code accepted. Both secrets are sealed by `services/sealing.py`, the AES-GCM/HKDF mechanism
lifted out of the Connections service so the two share it, each under its own derivation context.

The API gains four routes behind the admin dependency: `GET /api/auth/two-factor`,
`POST /api/auth/two-factor/enrollment`, `.../activation` and `.../disable`. `POST /api/auth/login`
and `POST /api/auth/password` each gain an optional `code`.

Notes and deviations:

- **`code_required` is a 401, not a 200.** The body carries `"result": "code_required"` beside
  `detail`. A client that predates two-factor reads any 200 from login as "logged in"; a non-2xx
  cannot be mistaken for a session. The other refusals carry `result` too (`wrong_password`,
  `wrong_code`); `detail` for a wrong password is unchanged.
- **The password is judged first.** `code_required` and `wrong_code` are only said to someone who
  already holds the password, and a wrong code counts as a failed attempt under ADR 0015's
  throttle — so a leaked password does not buy unmetered guesses at the code. A right password
  that still owes its code is neither: the second step may follow at once, but the attempt stays
  counted, so asking again without a code never resets the delay wrong codes have earned.
- **A code is accepted once.** The step of each accepted code is recorded, so a code that was
  watched cannot be replayed. The visible consequence: the code that logged the Admin in will not
  also change their password; the refusal says to wait for the next one.
- **Activation revokes every other Session**, keeping the caller's — each was opened by the
  password alone. Not in the ticket; it follows from what the second factor is for.
- **The in-app disable takes the password and a current code.** Removing a factor is a credential
  change and is held to what changing the password is held to.
- **The server-side disable** is `pnpm auth:disable-two-factor`
  (`python -m open_leprechaun.disable_two_factor`), documented in `docs/runbook.md` — a new file,
  linked from the README's command table and Authentication section. It clears the secret and any
  pending enrollment and touches nothing else. Unlike the seed it runs in production; that is
  where it is needed.
- **A changed `APPLICATION_SECRET` locks two-factor**, since the stored secret no longer opens. No
  code verifies; the server-side disable is the way back, and the runbook says so.
- **The QR code is drawn in the browser** (`uqr`, no transitive dependencies), from the URI the
  API returns. The secret never becomes an image fetched from anywhere.
- **Enrollment can be abandoned.** The pending secret stays in the row, inert, until the next
  enrollment replaces it; it cannot be activated without a code made from it.
- **The reminder** is a strip under the shell header on every page, production only, with no
  dismiss control. It shows only once the API has said two-factor is off — an unknown state shows
  nothing rather than a warning that may be false.
- **The proofs behind a live session are throttled too.** Changing the password and the in-app
  disable count against the same per-address record as login, so a stolen session and the password
  together still cannot run through the codes. This also closes the unthrottled current-password
  check ticket 60 left open. Both routes can now answer 429 with `Retry-After`.
- The Playwright journeys were extended in `e2e/security.spec.ts` against the same production
  stand-in ticket 60 used, but **were not run**: the browser cannot launch on the machine this was
  built on. The behaviour is covered at the API seam against Postgres.
