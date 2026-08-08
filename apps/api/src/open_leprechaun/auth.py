"""Who is calling.

Development skips authentication entirely — the laptop has exactly one user,
and login friction there buys nothing. Production accepts a session token,
minted by ``routers/auth.py``'s login: the httpOnly cookie first, then an
``Authorization: Bearer`` header, so a browser and any future client share one
login. A presented token that fails falls through to the next; no token at
all, or none that names a live session, is a 401.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status

from open_leprechaun.db import EngineDep
from open_leprechaun.services import auth as sessions
from open_leprechaun.settings import Environment, SettingsDep

SESSION_COOKIE = "ol_session"
"""The cookie login sets; httpOnly, so only the server ever reads it."""


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. This application only ever has the one admin."""

    subject: str


_ADMIN = Principal(subject="admin")


def require_admin(
    request: Request, response: Response, settings: SettingsDep, engine: EngineDep
) -> Principal:
    """The dependency every non-public route hangs off.

    Public routes — health, meta, setup, login, the OpenAPI document — simply
    do not use it.
    """
    if settings.environment is Environment.development:
        return _ADMIN
    for token in presented_tokens(request):
        if sessions.authenticate(engine, token, settings.session_ttl):
            if request.cookies.get(SESSION_COOKIE) == token:
                # authenticate() slid the session's expiry forward; the
                # browser's copy must slide with it, or the cookie dies a TTL
                # after login no matter how recently the admin was here.
                set_session_cookie(response, token, settings.session_ttl)
            return _ADMIN
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def presented_tokens(request: Request) -> Iterator[str]:
    """Every token the request carries, cookie first, then the bearer header."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        yield cookie
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        yield token.strip()


def set_session_cookie(response: Response, token: str, ttl: timedelta) -> None:
    """The one shape of the session cookie, wherever it is (re)issued."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="lax")


AdminDep = Annotated[Principal, Depends(require_admin)]
