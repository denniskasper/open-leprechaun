"""First-run setup and the one login endpoint.

Login returns the token twice on purpose: as an httpOnly Secure cookie for the
browser and in the response body for any future bearer client. Both name the
same session, and `open_leprechaun.auth.require_admin` accepts either. The
password travels only in request bodies — never a query string, so it cannot
land in an access log — and no response ever carries it or its hash.

While two-factor is active (ADR-0005) the same login endpoint answers a
distinct `code_required` to a right password that came alone; the client asks
again with the code, and the token it then receives is the unchanged one.
"""

import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from open_leprechaun.auth import (
    AdminDep,
    clear_session_cookie,
    presented_tokens,
    set_session_cookie,
)
from open_leprechaun.db import EngineDep
from open_leprechaun.services import auth as service
from open_leprechaun.services import two_factor
from open_leprechaun.settings import SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])


MINIMUM_PASSWORD_LENGTH = 12

# A floor, not a policy engine: long enough to rule out the trivially
# guessable, capped so a pathological input cannot stall the KDF. The one
# constraint every endpoint that *sets* a password shares.
NewPassword = Annotated[str, Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)]


# Generous on purpose: an authenticator shows "123 456" and the Admin may type
# it so. What a code must *be* is the service's to judge; this only bounds it.
Code = Annotated[str, Field(min_length=1, max_length=16)]

Clock = Callable[[], datetime]


def get_clock() -> Clock:
    """The instant a login or a code is judged at; a dependency so a test can
    move it through a backoff or a code's lifetime instead of waiting one out."""
    return lambda: datetime.now(UTC)


ClockDep = Annotated[Clock, Depends(get_clock)]


def _source_address(request: Request) -> str:
    """The address failed credential proofs are counted against (ADR-0015).

    The peer as the server sees it. Behind a reverse proxy that is the
    client only when uvicorn is told to trust the proxy's forwarded headers
    (`--proxy-headers --forwarded-allow-ips`); otherwise every caller shares
    the proxy's address and one count. A forwarded header is never read here
    directly — an attacker could mint a fresh address per guess.
    """
    return request.client.host if request.client else "unknown"


# One sentence for every refused code. "Already used" is said because it is
# the likely cause for an honest Admin: a code is accepted once, so the one
# that just logged them in will not also change their password.
_WRONG_CODE = "Wrong code, or one already used. Wait for the next code and try again."


_TOO_MANY_PROOFS = "Too many failed attempts from this address."

_LOGIN_REFUSALS = {
    service.LoginRefusal.wrong_password: "Wrong password.",
    service.LoginRefusal.code_required: "Enter the code from your authenticator app.",
    service.LoginRefusal.wrong_code: _WRONG_CODE,
}

_THROTTLED = {"description": "This address is waiting out earlier failures; see Retry-After"}


def _throttled(throttled: service.LoginThrottledError, what: str) -> HTTPException:
    """The 429 of an attempt made inside a delay. The same words whatever was
    presented: none of it was looked at."""
    seconds = max(1, math.ceil(throttled.retry_after.total_seconds()))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"{what} Try again in {seconds} second{'' if seconds == 1 else 's'}.",
        headers={"Retry-After": str(seconds)},
    )


def _wrong_code() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_WRONG_CODE)


class SetupStatusResponse(BaseModel):
    required: bool


class SetupRequest(BaseModel):
    password: NewPassword


class LoginRequest(BaseModel):
    # No floor here: an existing password is whatever setup accepted.
    password: str = Field(max_length=256)
    code: Code | None = Field(
        default=None, description="The authenticator's current code, once login has asked for it"
    )


class ChangePasswordRequest(BaseModel):
    # Like login, no floor on the current one: it is whatever was accepted.
    current_password: str = Field(max_length=256)
    new_password: NewPassword
    code: Code | None = Field(
        default=None, description="The authenticator's current code; owed while two-factor is on"
    )


class LoginRefusedResponse(BaseModel):
    detail: str
    result: service.LoginRefusal


class TwoFactorResponse(BaseModel):
    enabled: bool


class EnrollmentResponse(BaseModel):
    secret: str = Field(description="The shared secret, base32 — shown this once and never again")
    uri: str = Field(description="The otpauth:// URI an authenticator reads from a QR code")


class CodeRequest(BaseModel):
    code: Code


class DisableTwoFactorRequest(BaseModel):
    current_password: str = Field(max_length=256)
    code: Code


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
        status.HTTP_401_UNAUTHORIZED: {
            "model": LoginRefusedResponse,
            "description": (
                "No session was issued; `result` says why. `code_required` is not an"
                " error to show: the password was right, and the same request repeated"
                " with `code` completes the login."
            ),
        },
        status.HTTP_409_CONFLICT: {"description": "Setup has not run yet"},
        status.HTTP_429_TOO_MANY_REQUESTS: _THROTTLED,
    },
)
def log_in(
    body: LoginRequest,
    request: Request,
    response: Response,
    engine: EngineDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> LoginResponse | JSONResponse:
    try:
        session = service.log_in(
            engine,
            settings,
            body.password,
            body.code,
            address=_source_address(request),
            now=clock(),
        )
    except service.SetupRequiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has not run yet; there is no admin to log in.",
        ) from None
    except service.LoginThrottledError as throttled:
        raise _throttled(throttled, "Too many failed logins from this address.") from None
    if isinstance(session, service.LoginRefusal):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": _LOGIN_REFUSALS[session], "result": session.value},
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
        status.HTTP_403_FORBIDDEN: {
            "description": "Wrong current password, or a missing or wrong two-factor code"
        },
        status.HTTP_409_CONFLICT: {"description": "Setup has not run yet"},
        status.HTTP_429_TOO_MANY_REQUESTS: _THROTTLED,
    },
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> None:
    try:
        service.change_password(
            engine,
            settings,
            body.current_password,
            body.new_password,
            body.code,
            keep_token=admin.session_token,
            address=_source_address(request),
            now=clock(),
        )
    except service.LoginThrottledError as throttled:
        raise _throttled(throttled, _TOO_MANY_PROOFS) from None
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
    except service.CodeRequiredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Two-factor is on: changing the password takes a current code as well.",
        ) from None
    except two_factor.WrongCodeError:
        raise _wrong_code() from None


@router.get(
    "/two-factor",
    summary="Report whether two-factor is on",
    response_model=TwoFactorResponse,
)
def read_two_factor(admin: AdminDep, engine: EngineDep) -> TwoFactorResponse:
    return TwoFactorResponse(enabled=two_factor.active(engine))


@router.post(
    "/two-factor/enrollment",
    summary="Issue a secret for an authenticator app; nothing is enforced until a code proves it",
    status_code=status.HTTP_201_CREATED,
    response_model=EnrollmentResponse,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Two-factor is already on, or setup has not run yet"
        }
    },
)
def enroll_two_factor(
    admin: AdminDep, engine: EngineDep, settings: SettingsDep
) -> EnrollmentResponse:
    # The one response that ever carries the secret. Asking again issues a
    # new one and forgets the last, so an abandoned enrollment leaves nothing
    # that could later be activated.
    try:
        enrollment = two_factor.enroll(engine, settings)
    except two_factor.AlreadyActiveError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor is already on. Disable it before setting it up again.",
        ) from None
    except two_factor.NoAdminError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has not run yet; there is no admin to protect.",
        ) from None
    return EnrollmentResponse(secret=enrollment.secret, uri=enrollment.uri)


@router.post(
    "/two-factor/activation",
    summary="Turn two-factor on with a code that proves the enrollment works",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "The code does not verify"},
        status.HTTP_409_CONFLICT: {"description": "No enrollment is waiting for a code"},
    },
)
def activate_two_factor(
    body: CodeRequest, admin: AdminDep, engine: EngineDep, settings: SettingsDep, clock: ClockDep
) -> None:
    try:
        service.activate_two_factor(
            engine, settings, body.code, keep_token=admin.session_token, now=clock()
        )
    except two_factor.NoEnrollmentError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No enrollment is waiting for a code. Start setting two-factor up again.",
        ) from None
    except two_factor.WrongCodeError:
        raise _wrong_code() from None


@router.post(
    "/two-factor/disable",
    summary="Turn two-factor off, given the password and a current code",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Wrong current password or code"},
        status.HTTP_409_CONFLICT: {"description": "Two-factor is not on"},
        status.HTTP_429_TOO_MANY_REQUESTS: _THROTTLED,
    },
)
def disable_two_factor(
    body: DisableTwoFactorRequest,
    request: Request,
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> None:
    # The in-app disable still takes both factors. The way out for an Admin
    # who has lost theirs is the server-side one (docs/runbook.md).
    try:
        service.disable_two_factor(
            engine,
            settings,
            body.current_password,
            body.code,
            address=_source_address(request),
            now=clock(),
        )
    except service.LoginThrottledError as throttled:
        raise _throttled(throttled, _TOO_MANY_PROOFS) from None
    except two_factor.NotActiveError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Two-factor is not on."
        ) from None
    except service.WrongPasswordError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Wrong current password."
        ) from None
    except two_factor.WrongCodeError:
        raise _wrong_code() from None


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
