# 07 — First-run setup and login

**What to build:** A fresh deployment refuses to serve anything until an admin password is set, and thereafter one login endpoint serves both a browser and any future client.

**Blocked by:** 03, 04

**Status:** ready-for-agent

- [ ] With no admin present outside development, every route redirects to the setup screen
- [ ] Setup can run only once; a second attempt with an admin present is refused
- [ ] The password is hashed with a modern key-derivation function, never logged and never returned
- [ ] Login issues an httpOnly cookie and returns the same token in the response body
- [ ] The authentication dependency accepts the cookie first, then a bearer header
- [ ] Token lifetime and renewal behaviour are documented and configurable
