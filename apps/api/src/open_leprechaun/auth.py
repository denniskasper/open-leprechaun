"""Who is calling.

Development skips authentication entirely — the laptop has exactly one user,
and login friction there buys nothing. Production requires it. The login that
will satisfy this requirement is a later ticket; until it lands, production
answers 401 to every protected request, which is the safe direction to fail.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from open_leprechaun.settings import Environment, SettingsDep


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. This application only ever has the one admin."""

    subject: str


_DEVELOPMENT_ADMIN = Principal(subject="admin")


def require_admin(settings: SettingsDep) -> Principal:
    """The dependency every non-public route hangs off.

    Public routes — health, meta, the OpenAPI document — simply do not use it.
    """
    if settings.environment is Environment.development:
        return _DEVELOPMENT_ADMIN
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


AdminDep = Annotated[Principal, Depends(require_admin)]
