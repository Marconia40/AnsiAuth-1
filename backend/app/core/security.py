from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ELEVATED_TOKEN_EXPIRE_MINUTES,
    JWT_SECRET_KEY,
)

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY must be set in .env")

if ACCESS_TOKEN_EXPIRE_MINUTES <= 0 or ACCESS_TOKEN_EXPIRE_MINUTES > 60:
    raise RuntimeError(
        f"ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 60, got: {ACCESS_TOKEN_EXPIRE_MINUTES}"
    )

ALGORITHM = "HS256"

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_ELEVATED = "elevated"


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])


def create_elevated_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "typ": TOKEN_TYPE_ELEVATED,
        "iat": now,
        "exp": now + timedelta(minutes=ELEVATED_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=ALGORITHM)


def verify_elevated_token(token: str, expected_username: str) -> None:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("elevated_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("elevated_invalid") from exc

    if payload.get("typ") != TOKEN_TYPE_ELEVATED:
        raise ValueError("elevated_invalid")
    sub = (payload.get("sub") or "").lower()
    if sub != (expected_username or "").lower():
        raise ValueError("elevated_mismatch")
