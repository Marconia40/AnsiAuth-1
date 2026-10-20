from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional, TypedDict

from sqlalchemy import event, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class UserContext(TypedDict, total=False):
    id: Optional[int]
    is_system_admin: bool


current_user_ctx: ContextVar[UserContext] = ContextVar(
    "current_user_ctx", default={}
)

_system_context_active: ContextVar[bool] = ContextVar(
    "_system_context_active", default=False
)


@contextmanager
def system_context():
    token = _system_context_active.set(True)
    try:
        yield
    finally:
        _system_context_active.reset(token)


@contextmanager
def sin_contexto_de_sistema():
    token = _system_context_active.set(False)
    try:
        yield
    finally:
        _system_context_active.reset(token)


def resolve_current_gucs() -> tuple[int, bool]:
    if _system_context_active.get():
        return (0, True)
    user = current_user_ctx.get() or {}
    uid = user.get("id") or 0
    is_sys = bool(user.get("is_system_admin", False))
    return (int(uid), is_sys)


def install_session_rls_hook(session_factory) -> None:
    @event.listens_for(session_factory, "after_begin")
    def _apply_rls_gucs(session: Session, _transaction, connection):
        if connection is None or connection.dialect.name != "postgresql":
            return
        uid, is_sys = resolve_current_gucs()
        connection.execute(
            text("SELECT set_config('app.user_id', :uid, true)"),
            {"uid": str(uid)},
        )
        connection.execute(
            text("SELECT set_config('app.is_system_admin', :sa, true)"),
            {"sa": "true" if is_sys else "false"},
        )

    logger.debug("RLS session hook installed")


def install_worker_system_context() -> None:
    _system_context_active.set(True)
    logger.info("RLS: worker process pinned to system context")
