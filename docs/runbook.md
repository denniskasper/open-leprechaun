# Runbook

What to do when the running instance needs a hand from the host. Each entry says when it applies,
the command, and how to tell it worked.

## Locked out by two-factor

**When:** the Admin's password is known, but login keeps asking for a code that cannot be
produced or is never accepted — the authenticator is lost, wiped or replaced, the secret was never
saved to a password store, or `APPLICATION_SECRET` changed and the stored secret no longer
decrypts.

There are no recovery codes (ADR-0005). The way back in is to turn two-factor off from the host,
which needs what someone holding only the password does not have: a shell on the server and access
to the database.

**Before reaching for it**, rule out the cheap causes:

- The authenticator's clock. Codes are time-based and accepted for about thirty seconds either
  side of the server's time; a phone whose clock is minutes out produces codes that never verify.
  Turn automatic time on and try the next code.
- A reused code. Each code is accepted once. Wait for the next one.
- The login delay. Failed attempts from one address delay the next, up to five minutes (ADR-0015).
  A `429` is that delay, not a lock — wait it out and try again.
- The secret in a password store. If it was saved at enrollment, add it to a new authenticator and
  log in normally; nothing needs disabling.

**The command.** Run it where the API runs, with the instance's own environment — the same
`ENVIRONMENT`, `DATABASE_URL` and `APPLICATION_SECRET` the API itself starts with. A checkout reads
them from `.env`; anywhere else they must be set, or the command stops on a settings error before
it touches anything:

```sh
# From a checkout:
pnpm auth:disable-two-factor

# Anywhere the API's Python environment is — a container included:
python -m open_leprechaun.disable_two_factor
```

The deployed instance runs in a container, so run the second form inside it, where it inherits the
container's environment. On the server, with the name `docker ps --filter name=-api-1` shows
(`docs/deployment.md`):

```sh
docker exec -it <service>-api-1 python -m open_leprechaun.disable_two_factor
```

**What it does.** Clears the Admin's two-factor secret and any unfinished enrollment. Nothing
else: the password is unchanged, open Sessions stay open, and no ledger data is touched. It asks
for no code and no password, and it is safe to run twice.

**How to tell it worked.** It prints `Two-factor is disabled.` (or `Two-factor was not enabled;
nothing changed.` if there was nothing to remove). Log in with the password alone.

**Afterwards.**

1. Set two-factor up again under Settings → Security. The reminder shown on every page stays until
   it is on.
2. Save the new secret to a password store this time — that is what makes losing a phone a
   non-event.
3. If the lockout came from a device that may be in someone else's hands, change the password
   too, and sign out everywhere.
