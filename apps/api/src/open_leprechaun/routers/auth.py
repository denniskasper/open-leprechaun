"""First-run setup and the one login endpoint.

Login returns the token twice on purpose: as an httpOnly Secure cookie for the
browser and in the response body for any future bearer client. Both name the
same session, and `open_leprechaun.auth.require_admin` accepts either. The
password travels only in request bodies — never a query string, so it cannot
land in an access log — and no response ever carries it or its hash.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from open_leprechaun.auth import (
    AdminDep,
    clear_session_cookie,
    presented_tokens,
    set_session_cookie,
)
from open_leprechaun.db import EngineDep
from open_leprechaun.services import auth as service
from open_leprechaun.settings import SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])


MINIMUM_PASSWORD_LENGTH = 12

# A floor, not a policy engine: long enough to rule out the trivially
# guessable, capped so a pathological input cannot stall the KDF. The one
# constraint every endpoint that *sets* a password shares.
NewPassword = Annotated[str, Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)]


class SetupStatusResponse(BaseModel):
    required: bool


class SetupRequest(BaseModel):
    password: NewPassword


class LoginRequest(BaseModel):
    # No floor here: an existing password is whatever setup accepted.
    password: str = Field(max_length=256)


class ChangePasswordRequest(BaseModel):
    # Like login, no floor on the current one: it is whatever was accepted.
    current_password: str = Field(max_length=256)
    new_password: NewPassword


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime


class SessionResponse(BaseModel):
    subject: str


class SessionCountResponse(BaseModel):
    active: int


@router.get(
    "/setup",
    summary="Report whether first-run setup still has to happen",
    response_model=SetupStatusResponse,
)
def read_setup_status(engine: EngineDep) -> SetupStatusResponse:
    # Public on purpose: the web client asks this before anyone can log in,
    # and "an admin exists" is not a secret.
    return SetupStatusResponse(required=service.setup_required(engine))


@router.post(
    "/setup",
    summary="Set the admin password, exactly once per instance",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "The admin already exists"}},
)
def run_setup(body: SetupRequest, engine: EngineDep) -> None:
    try:
        service.set_up_admin(engine, body.password)
    except service.SetupAlreadyDoneError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already run; this instance has its admin.",
        ) from None


@router.post(
    "/login",
    summary="Exchange the password for a session, as cookie and bearer token both",
    response_model=LoginResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Wrong password"},
        status.HTTP_409_CONFLICT: {"description": "Setup has not run yet"},
    },
)
def log_in(
    body: LoginRequest, response: Response, engine: EngineDep, settings: SettingsDep
) -> LoginResponse:
    try:
        session = service.log_in(engine, body.password, settings.session_ttl)
    except service.SetupRequiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has not run yet; there is no admin to log in.",
        ) from None
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong password.",
        )
    set_session_cookie(response, session.token, settings.session_ttl)
    return LoginResponse(token=session.token, expires_at=session.expires_at)


@router.post(
    "/logout",
    summary="Revoke the presented session and clear the cookie",
    status_code=status.HTTP_204_NO_CONTENT,
)
def log_out(request: Request, response: Response, engine: EngineDep) -> None:
    # Public rather than admin-gated: revoking requires possessing the token,
    # and an already-expired session still deserves a cleared cookie.
    for token in presented_tokens(request):
        service.log_out(engine, token)
    clear_session_cookie(response)


@router.post(
    "/password",
    summary="Change the admin password, revoking every other session",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Wrong current password"},
        status.HTTP_409_CONFLICT: {"description": "Setup has not run yet"},
    },
)
def change_password(body: ChangePasswordRequest, admin: AdminDep, engine: EngineDep) -> None:
    try:
        service.change_password(
            engine, body.current_password, body.new_password, keep_token=admin.session_token
        )
    except service.SetupRequiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has not run yet; there is no password to change.",
        ) from None
    except service.WrongPasswordError:
        # 403, not 401: the session is fine, and a client that treats 401 as
        # "logged out" must not throw the admin out over a typo.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wrong current password.",
        ) from None


@router.get(
    "/sessions",
    summary="Count the sessions that are currently live",
    response_model=SessionCountResponse,
)
def count_sessions(admin: AdminDep, engine: EngineDep) -> SessionCountResponse:
    # A count, not a list: a session records no device or address, so a list
    # would be identical anonymous rows.
    return SessionCountResponse(active=service.count_active_sessions(engine))


@router.delete(
    "/sessions",
    summary="Revoke every session, the caller's included, and clear the cookie",
    status_code=status.HTTP_204_NO_CONTENT,
)
def log_out_everywhere(admin: AdminDep, response: Response, engine: EngineDep) -> None:
    # Admin-gated, unlike logout: this revokes sessions the caller does not
    # hold the tokens of.
    service.log_out_everywhere(engine)
    clear_session_cookie(response)


@router.get(
    "/session",
    summary="Name the authenticated caller",
    response_model=SessionResponse,
)
def read_session(admin: AdminDep) -> SessionResponse:
    # The web client's "am I logged in" probe; development answers yes.
    return SessionResponse(subject=admin.subject)
