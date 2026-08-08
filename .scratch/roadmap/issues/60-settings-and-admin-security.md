# 60 — Settings and Admin security

**What to build:** The settings convention every later panel inherits, proven by building one real panel in it — Security, where the Admin signs out, changes their password, and sees how many sessions are open. Ticket 07 minted sessions that only the API can revoke; this ticket gives the Admin the controls.

Establish the panel shape once so no later settings ticket invents its own.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] A settings panel convention — heading, description, grouped controls — documented for tickets 08, 09, 10 and 42 to reuse
- [ ] `Settings → Security` registered in `navigation.ts`; `/settings` redirects to the first panel rather than rendering an index
- [ ] Sign out of the current session from the app shell header, on every page and on mobile
- [ ] Sign out everywhere from the Security panel, revoking every session including the current one
- [ ] Either path clears the client query cache, so no answer from the old session survives the transition
- [ ] `POST /api/auth/password` takes the current password and a new one; a wrong current password is refused
- [ ] Changing the password revokes every other session and keeps the current one alive
- [ ] The 12-character minimum is one shared constraint used by both setup and change, with a test that both endpoints refuse an 11-character password
- [ ] The Security panel shows the count of active sessions
- [ ] **Admin** and **Session** are added to `CONTEXT.md`

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
