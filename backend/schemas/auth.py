"""Password-account request and response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class CredentialsRequest(BaseModel):
    username: str = ""
    password: str = ""


class AccountUpdateRequest(BaseModel):
    current_password: str = ""
    username: str | None = None
    new_password: str | None = None


class UserResponse(BaseModel):
    username: str
