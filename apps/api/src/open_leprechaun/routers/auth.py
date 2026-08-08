"""First-run setup and the one login endpoint.

Login returns the token twice on purpose: as an httpOnly Secure cookie for the
browser and in the response body for any future bearer client. Both name the
same session, and `open_leprechaun.auth.require_admin` accepts either. The
password travels only in request bodies — never a query string, so it cannot
land in an access log — and no response ever carries it or its hash.
"""

from datetime import datetime

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


class SetupStatusResponse(BaseModel):
    required: bool


class SetupRequest(BaseModel):
    # A floor, not a policy engine: long enough to rule out the trivially
    # guessable, capped so a pathological input cannot stall the KDF.
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    # No floor here: an existing password is whatever setup accepted.
    password: str = Field(max_length=256)


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime


class SessionResponse(BaseModel):
    subject: str


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


@router.get(
    "/session",
    summary="Name the authenticated caller",
    response_model=SessionResponse,
)
def read_session(admin: AdminDep) -> SessionResponse:
    # The web client's "am I logged in" probe; development answers yes.
    return SessionResponse(subject=admin.subject)
