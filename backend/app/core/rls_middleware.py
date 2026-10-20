from __future__ import annotations

import logging
import threading
import time as _time
from typing import Optional

from jwt import PyJWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import RATE_LIMIT_LOGIN, RATE_LIMIT_PER_IP, RATE_LIMIT_PER_USER
from app.core.rls_context import UserContext, current_user_ctx, sin_contexto_de_sistema
from app.core.security import verify_token

logger = logging.getLogger(__name__)


LOGIN_RATE_LIMIT_RPM: int = RATE_LIMIT_LOGIN
RATE_LIMIT_PER_IP_RPM: int = RATE_LIMIT_PER_IP
RATE_LIMIT_PER_USER_RPM: int = RATE_LIMIT_PER_USER
WINDOW_SECONDS: float = 60.0

_buckets: dict[str, list[float]] = {}
_lock = threading.Lock()

_LOGIN_PATH = "/api/v1/auth/login"
_EXCLUDED_PATHS: frozenset[str] = frozenset({"/health"})


def is_excluded(path: str) -> bool:
    return path in _EXCLUDED_PATHS


def _get_now() -> float:
    return _time.time()


def reset() -> None:
    with _lock:
        _buckets.clear()


def _check_and_record(key: str, limit: int) -> tuple[bool, int]:
    now = _get_now()
    cutoff = now - WINDOW_SECONDS
    with _lock:
        bucket = _buckets.setdefault(key, [])
        _buckets[key] = [t for t in bucket if t > cutoff]
        if len(_buckets[key]) >= limit:
            oldest = min(_buckets[key])
            retry_after = max(int(oldest + WINDOW_SECONDS - now) + 1, 1)
            return False, retry_after
        _buckets[key].append(now)
        return True, 0


def bucket_for(request: Request, username: "str | None") -> tuple[str, int]:
    ip = request.client.host if request.client else "unknown"
    if request.url.path == _LOGIN_PATH:
        return f"login:{ip}", LOGIN_RATE_LIMIT_RPM
    if username:
        return f"user:{username}", RATE_LIMIT_PER_USER_RPM
    return f"ip:{ip}", RATE_LIMIT_PER_IP_RPM


def decode_bearer(request: Request) -> "tuple[Optional[dict], Optional[str]]":
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None, "Not authenticated"
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = verify_token(token)
    except PyJWTError:
        return None, "Invalid or expired token"
    if not payload.get("sub"):
        return None, "Invalid token payload"
    return payload, None


def _lookup_user(username: str) -> "tuple[int, bool, bool] | None":
    from app.core.rls_context import system_context
    from app.db.models import UserModel
    from app.db.session import get_session

    try:
        with system_context():
            with get_session() as session:
                row = (
                    session.query(UserModel.id, UserModel.is_active, UserModel.is_system_admin)
                    .filter(UserModel.username == username.lower())
                    .first()
                )
                return (int(row[0]), bool(row[1]), bool(row[2])) if row is not None else None
    except Exception:  # pragma: no cover — defensive: never break the request
        logger.warning("AuthContextMiddleware: failed to resolve user id for %s", username)
        return None


def _to_rls_ctx(payload: "dict | None", user_id: "int | None") -> UserContext:
    if payload is None:
        return {}
    is_sys = payload.get("is_system_admin")
    if is_sys is None:
        is_sys = (payload.get("role") or "").lower() in {"admin", "super-admin"}
    return {"id": user_id, "is_system_admin": bool(is_sys)}


class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        payload, error = decode_bearer(request)
        username = payload.get("sub") if payload else None
        user_row = _lookup_user(username) if username else None

        request.state.auth_resolved = True
        request.state.auth_payload = payload
        request.state.auth_error = error
        request.state.auth_user_row = user_row

        rls_token = current_user_ctx.set(
            _to_rls_ctx(payload, user_row[0] if user_row is not None else None)
        )
        try:
            if not is_excluded(request.url.path):
                key, limit = bucket_for(request, username)
                allowed, retry_after = _check_and_record(key, limit)
                if not allowed:
                    from app.schemas.error import make_error
                    from starlette.responses import JSONResponse

                    return JSONResponse(
                        status_code=429,
                        content=make_error(429, "Too many requests", "RATE_LIMIT_EXCEEDED"),
                        headers={"Retry-After": str(retry_after)},
                    )
            with sin_contexto_de_sistema():
                return await call_next(request)
        finally:
            current_user_ctx.reset(rls_token)
