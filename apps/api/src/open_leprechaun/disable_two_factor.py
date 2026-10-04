"""The server-side disable of two-factor: `pnpm auth:disable-two-factor`.

ADR-0005 issues no recovery codes; this is the anti-lockout path the
enrollment screen promises. It needs what an attacker with only the password
does not have — a shell on the host and the database — and asks for nothing
else: no code, no password. See `docs/runbook.md`.

The password is untouched and so is every session; the next login simply
needs no code, and two-factor can be set up again from Settings → Security.
"""

import sys

from sqlalchemy import Engine, create_engine

from open_leprechaun.services import two_factor
from open_leprechaun.settings import get_settings


def disable(engine: Engine) -> str:
    """Remove the second factor and say what that came to."""
    if two_factor.remove(engine):
        return (
            "Two-factor is disabled. Log in with the password alone, then set"
            " two-factor up again under Settings → Security."
        )
    return "Two-factor was not enabled; nothing changed."


def main() -> int:
    engine = create_engine(get_settings().database_url)
    try:
        print(disable(engine))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
