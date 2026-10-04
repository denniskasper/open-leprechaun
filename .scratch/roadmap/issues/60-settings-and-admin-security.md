# 60 — Settings and Admin security

**What to build:** The settings convention every later panel inherits, proven by building one real panel in it — Security, where the Admin signs out, changes their password, and sees how many sessions are open. Ticket 07 minted sessions that only the API can revoke; this ticket gives the Admin the controls.

Establish the panel shape once so no later settings ticket invents its own.

**Blocked by:** 07

**Status:** done

- [x] A settings panel convention — heading, description, grouped controls — documented for tickets 08, 09, 10 and 42 to reuse
- [x] `Settings → Security` registered in `navigation.ts`; `/settings` redirects to the first panel rather than rendering an index
- [x] Sign out of the current session from the app shell header, on every page and on mobile
- [x] Sign out everywhere from the Security panel, revoking every session including the current one
- [x] Either path clears the client query cache, so no answer from the old session survives the transition
- [x] `POST /api/auth/password` takes the current password and a new one; a wrong current password is refused
- [x] Changing the password revokes every other session and keeps the current one alive
- [x] The 12-character minimum is one shared constraint used by both setup and change, with a test that both endpoints refuse an 11-character password
- [x] The Security panel shows the count of active sessions
- [x] **Admin** and **Session** are added to `CONTEXT.md`

## Notes

**Why "Security" and not "Account".** `CONTEXT.md` defines **Account** as one holding under a
Platform and the boundary for FIFO lot matching, with an explicit _Avoid_ against using the word
for a credentialed link. The Admin-identity area cannot be called an account in this project
without breaking the ubiquitous language.

**No session list.** `admin_session` records a token digest, an admin id and an expiry — no
device, address or last-seen column. A list would render identical anonymous rows, which reads
worse than no list, and adding the metadata to populate one is a privacy decision this ticket
does not take. The count is the honest signal that "sign out everywhere" has work to do.

**Requiring the current password** is what stops someone at an unlocked laptop. Revoking the
other sessions is the point of changing a password after a suspected leak; keeping the current
one alive avoids making the Admin log in again immediately after proving who they are.

**Session lifetime stays env-only.** `SESSION_TTL_HOURS` is deployment policy, not a credential,
and a wrong value set in a UI is silent and long-lived. Out of scope deliberately.

**Two-factor is not in scope** — ticket 08 owns it and now blocks on this ticket for somewhere to
live. `POST /api/auth/password` takes no code field until 08 adds one, which is a backwards-
compatible MINOR change under `docs/agents/versioning.md`; a field shipped now and ignored would
be a lie in the API surface.

## Comments

Implemented (2026-10-04). The convention is two components in
`components/patterns/settings-panel.tsx` — `SettingsPanel` (heading, description) and
`SettingsGroup` (a named group of controls) — documented in `docs/agents/design.md` § Settings
panels, with Security as the reference panel. `/settings` redirects to `SETTINGS_INDEX`, the first
panel declared in `navigation.ts`.

The API gains three routes, all behind the admin dependency: `POST /api/auth/password`,
`GET /api/auth/sessions` (the count) and `DELETE /api/auth/sessions` (sign out everywhere, which
also clears the cookie). The password swap and the revocation of the other sessions are one
transaction. The 12-character floor is the `NewPassword` type both request models use.

Notes and deviations:

- A wrong current password is a 403, not a 401: the session is fine, and a client that reads 401
  as "logged out" must not eject the Admin over a typo.
- The authenticated principal now carries the token that authenticated it, which is how the
  change knows which session to keep. Development authenticates nobody, so there it keeps none.
- Development has no Session to end. The header's sign out appears only where a session exists,
  and the Security panel says in words that there is nothing to secure rather than offering
  controls that would do nothing.
- Signing out drops the whole query cache and lands on `/login`. The header shows a short alert
  if the revocation itself fails, rather than pretending to have signed out.
- The existing settings screens (Platforms, Connections, Statutory, Scheduled tasks) predate the
  convention and were not rebuilt on it here; that is follow-up work.
- The Playwright journeys run against the dev-mode harness with the auth endpoints answered by a
  stand-in that presents the instance as production — the production-mode harness ticket 07
  deferred is still outstanding. Revocation itself is covered at the API seam against Postgres.
- The current-password check is as unthrottled as login is today. It sits behind a live session,
  but ticket 61 should count it among the surfaces it throttles.
- Signing out everywhere with a session that has already died is treated by the web as signed
  out — the Admin lands on login rather than on an error — though nothing was revoked elsewhere.
- **Admin** and **Session** were already in `CONTEXT.md`; no change was needed.
