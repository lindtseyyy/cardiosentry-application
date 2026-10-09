"""Sign-in routes and capture ownership checks."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Response

from backend.api.state import get_state
from backend.errors import ApiError, NotFound
from backend.schemas.auth import AccountUpdateRequest, CredentialsRequest, UserResponse
from backend.services import storage
from backend.services.accounts import Account, ADMIN_ACCOUNT_ID, SESSION_COOKIE, SESSION_TTL_DAYS

router = APIRouter(prefix="/auth", tags=["auth"])

PUBLIC_PATHS = frozenset({
    "/api/health", "/api/config", "/api/auth/login", "/api/auth/register",
    "/api/auth/logout",
})


def current_account(request: Request) -> Account:
    account = get_state(request).accounts.user_for_token(request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
    return account


def owned_capture(request: Request, capture_id: str) -> tuple[Path, dict]:
    account = current_account(request)
    record = get_state(request).records.owned_capture(capture_id, account.account_id)
    if record is None:
        raise NotFound("CAPTURE_NOT_FOUND", "That capture no longer exists.")
    try:
        directory = storage.capture_dir(capture_id)
    except KeyError:
        raise NotFound("CAPTURE_NOT_FOUND", "That capture no longer exists.") from None
    return directory, record


def _is_admin(account: Account) -> bool:
    return account.account_id == ADMIN_ACCOUNT_ID or account.username.lower() == "admin"


def _set_session_cookie(request: Request, response: Response, username: str) -> str:
    token = get_state(request).accounts.create_session(username)
    response.set_cookie(
        key=SESSION_COOKIE, value=token, max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/", secure=request.url.scheme == "https", httponly=True, samesite="lax",
    )
    return token

@router.post("/register", status_code=201, response_model=UserResponse)
def register(body: CredentialsRequest, request: Request, response: Response) -> UserResponse:
    username = get_state(request).accounts.register(body.username, body.password)
    _set_session_cookie(request, response, username)
    return UserResponse(username=username, is_admin=False)


@router.post("/login", response_model=UserResponse)
def login(body: CredentialsRequest, request: Request, response: Response) -> UserResponse:
    username = get_state(request).accounts.authenticate(body.username, body.password)
    token = _set_session_cookie(request, response, username)
    account = get_state(request).accounts.user_for_token(token)
    is_admin = _is_admin(account) if account is not None else username.strip().lower() == ADMIN_ACCOUNT_ID
    return UserResponse(username=username, is_admin=is_admin)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    get_state(request).accounts.revoke(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(
        key=SESSION_COOKIE, path="/", secure=request.url.scheme == "https",
        httponly=True, samesite="lax",
    )
    return {"logged_out": True}


@router.get("/me", response_model=UserResponse)
def me(request: Request) -> UserResponse:
    account = current_account(request)
    return UserResponse(username=account.username, is_admin=_is_admin(account))


@router.patch("/account", response_model=UserResponse)
def update_account(body: AccountUpdateRequest, request: Request) -> UserResponse:
    account = get_state(request).accounts.update_account(
        request.cookies.get(SESSION_COOKIE), body.current_password,
        username=body.username, new_password=body.new_password)
    return UserResponse(username=account.username, is_admin=_is_admin(account))
