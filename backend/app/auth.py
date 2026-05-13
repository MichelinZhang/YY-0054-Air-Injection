"""Authentication and authorization module for medical device software (ISO 13485).

Provides token-based authentication with role-based access control.
In development mode, auth can be disabled for convenience.
In production mode, auth is always enforced.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from enum import Enum
from typing import Any

from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import AUTH_ENABLED, AUTH_SECRET_KEY, AUTH_TOKEN_EXPIRE_HOURS
from app.errors import AppError, ErrorCode


class Role(str, Enum):
    OPERATOR = "operator"
    ENGINEER = "engineer"
    ADMIN = "admin"


ROLE_HIERARCHY = {
    Role.ADMIN: {Role.ADMIN, Role.ENGINEER, Role.OPERATOR},
    Role.ENGINEER: {Role.ENGINEER, Role.OPERATOR},
    Role.OPERATOR: {Role.OPERATOR},
}


class UserContext:
    """Represents the authenticated user in the current request."""

    def __init__(self, username: str, role: Role, token_issued_at: float) -> None:
        self.username = username
        self.role = role
        self.token_issued_at = token_issued_at

    def has_role(self, required: Role) -> bool:
        return required in ROLE_HIERARCHY.get(self.role, set())

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_engineer(self) -> bool:
        return self.role in (Role.ADMIN, Role.ENGINEER)


_ANONYMOUS_USER = UserContext(username="anonymous", role=Role.OPERATOR, token_issued_at=0.0)

_security = HTTPBearer(auto_error=False)


def generate_token(username: str, role: str) -> str:
    """Generate a signed token for the given user."""
    issued_at = time.time()
    payload = json.dumps({
        "sub": username,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + AUTH_TOKEN_EXPIRE_HOURS * 3600,
    }, separators=(",", ":"))
    signature = hmac.new(
        AUTH_SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}|{signature}"


def _verify_token(token: str) -> UserContext:
    """Verify token signature and expiration."""
    parts = token.rsplit("|", 1)
    if len(parts) != 2:
        raise AppError(401, ErrorCode.AUTH_TOKEN_INVALID, "Malformed token")

    payload_str, signature = parts
    expected_sig = hmac.new(
        AUTH_SECRET_KEY.encode(), payload_str.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        raise AppError(401, ErrorCode.AUTH_TOKEN_INVALID, "Invalid token signature")

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        raise AppError(401, ErrorCode.AUTH_TOKEN_INVALID, "Corrupted token payload")

    if time.time() > payload.get("exp", 0):
        raise AppError(401, ErrorCode.AUTH_TOKEN_EXPIRED, "Token has expired")

    role_str = payload.get("role", "operator")
    try:
        role = Role(role_str)
    except ValueError:
        role = Role.OPERATOR

    return UserContext(
        username=payload.get("sub", "unknown"),
        role=role,
        token_issued_at=payload.get("iat", 0.0),
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> UserContext:
    """FastAPI dependency: extract and verify the current user from the request."""
    if not AUTH_ENABLED:
        return _ANONYMOUS_USER

    if credentials is None:
        raise AppError(401, ErrorCode.AUTH_TOKEN_MISSING, "Authorization token required")

    return _verify_token(credentials.credentials)


def verify_ws_token(token: str | None) -> UserContext:
    """Verify token for WebSocket connections (cannot use standard Depends)."""
    if not AUTH_ENABLED:
        return _ANONYMOUS_USER
    if not token:
        raise AppError(401, ErrorCode.AUTH_TOKEN_MISSING, "Authorization token required for WebSocket")
    return _verify_token(token)


def require_role(required_role: Role):
    """Dependency factory: require at least the specified role."""
    async def checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not user.has_role(required_role):
            raise AppError(
                403,
                ErrorCode.AUTH_PERMISSION_DENIED,
                f"Role '{required_role.value}' or higher required",
            )
        return user
    return checker
