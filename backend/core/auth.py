"""
core/auth.py — JWT issuance and verification.

Single source of truth for all authentication operations.
The /auth/login endpoint issues tokens; decode_context() verifies them
on every request. No auth logic lives anywhere else.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

import config
from tools.base import ToolContext

_ALGORITHM = "HS256"
_EXPIRY_HOURS = 8

VALID_ROLES = {"employee", "hr_staff", "hr_manager", "admin"}


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def issue_jwt(user_id: str, role: str, tenant_id: str, employee_code: str, display_name: str) -> str:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "employee_code": employee_code or "",
        "display_name": display_name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_EXPIRY_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=_ALGORITHM)


def decode_context(token: str, expected_tenant_id: str) -> ToolContext:
    """Decode and validate a JWT. Raises AuthError on any failure."""
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("Token has expired. Please log in again.")
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid token: {exc}")

    if payload.get("tenant_id") != expected_tenant_id:
        raise AuthError("Token does not belong to this tenant.")

    role = payload.get("role", "")
    if role not in VALID_ROLES:
        raise AuthError(f"Unknown role in token: {role!r}")

    return ToolContext(
        tenant_id=expected_tenant_id,
        user_id=payload["sub"],
        role=role,
        employee_code=payload.get("employee_code", ""),
        display_name=payload.get("display_name", ""),
    )
