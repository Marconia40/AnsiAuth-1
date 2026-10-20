from __future__ import annotations

import json
import logging
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request

from app.core.exceptions import NotFoundError
from app.db.models import DeviceGroupModel, DeviceModel, SiteModel, UserModel
from app.db.session import get_session
from app.models.visibility_scope import VisibilityScope
from app.repositories.role_assignment_repository import RoleAssignmentRepository

logger = logging.getLogger(__name__)

OP_MIN_ROLE: dict[str, Tuple[str, str]] = {
    "read_device":                    ("device",       "observer"),
    "edit_device":                    ("device",       "admin"),
    "delete_device":                  ("device",       "admin"),
    "register_device":                ("site",         "admin"),
    "move_device_same_site":          ("device",       "operator"),
    "move_device_cross_site":         ("site",         "admin"),
    "retry_rollback":                 ("device",       "operator"),
    "cancel_job":                     ("device",       "operator"),
    "read_group":                     ("device_group", "observer"),
    "list_group_devices":             ("device_group", "observer"),
    "create_group":                   ("site",         "admin"),
    "edit_group":                     ("device_group", "admin"),
    "delete_group":                   ("device_group", "admin"),
    "read_site":                      ("site",         "observer"),
    "edit_site":                      ("site",         "admin"),
}


_ROLE_LEVEL: dict[str, int] = {
    "observer":    1,
    "operator":    2,
    "admin":       3,
    "super-admin": 99,
}


def get_current_user(request: Request) -> dict:
    if getattr(request.state, "auth_resolved", False):
        payload = request.state.auth_payload
        error = request.state.auth_error
    else:
        from app.core.rls_middleware import decode_bearer
        payload, error = decode_bearer(request)
    if payload is None:
        raise HTTPException(status_code=401, detail=error or "Not authenticated")
    username = payload.get("sub")
    is_sys = payload.get("is_system_admin")
    if is_sys is None:
        is_sys = (payload.get("role") or "").lower() in {"admin", "super-admin"}
    return {"username": username, "is_system_admin": bool(is_sys)}


def require_authenticated(
    current: dict = Depends(get_current_user), request: Request = None,
) -> dict:
    username = (current.get("username") or "").lower()
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    if request is not None and getattr(request.state, "auth_resolved", False):
        row = request.state.auth_user_row
    else:
        with get_session() as session:
            row = (
                session.query(UserModel.id, UserModel.is_active, UserModel.is_system_admin)
                .filter(UserModel.username == username)
                .first()
            )
    if row is None:
        return {**current, "id": None}
    if not row[1]:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return {**current, "id": int(row[0]), "is_system_admin": bool(row[2])}


def require_system_admin(current: dict = Depends(require_authenticated)) -> dict:
    if not current.get("is_system_admin"):
        raise HTTPException(
            status_code=403,
            detail="This operation requires system-admin privilege",
        )
    return current


def require_elevated(
    request: Request,
    current: dict = Depends(require_authenticated),
) -> dict:
    from app.core.security import verify_elevated_token

    token = request.headers.get("x-elevated-auth")
    if not token:
        raise HTTPException(status_code=401, detail="reauth_required")
    try:
        verify_elevated_token(token, current["username"])
    except ValueError:
        raise HTTPException(status_code=401, detail="reauth_required")
    return current


def obtener_scope(
    current: dict = Depends(require_authenticated),
) -> VisibilityScope:
    from app.composition import get_role_assignment_repo

    repo: RoleAssignmentRepository = get_role_assignment_repo()
    return repo.scope_de(current)


def require_scope(op: str):
    async def dep(
        request: Request,
        current: dict = Depends(require_authenticated),
        scope: VisibilityScope = Depends(obtener_scope),
    ) -> dict:
        if op == "move_device":
            await _authorize_move_device(request, current, scope)
            return current

        cfg = OP_MIN_ROLE.get(op)
        if cfg is None:
            raise HTTPException(status_code=500, detail=f"Unknown scope operation: {op}")
        scope_kind, min_role = cfg

        target = await _resolve_target(request, scope_kind)
        if target is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not resolve {scope_kind} target for operation "
                    f"'{op}' from path or body"
                ),
            )

        resolved = resolver_site_group(target, scope_kind)
        role = scope.rol_para(*resolved) if resolved is not None else None
        _enforce(role, min_role, op, scope_kind, target)
        return current

    return dep


async def _authorize_move_device(
    request: Request, current: dict, scope: VisibilityScope,
) -> None:
    name = request.path_params.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="move_device requires {name} in path")

    body = await _peek_json_body(request)
    body_group_id = body.get("device_group_id") if isinstance(body, dict) else None

    with get_session() as session:
        source = _lookup_device_scope(session, name)
        if source is None:
            raise HTTPException(status_code=404, detail=f"Device '{name}' not found")
        src_site_id, src_group_id = source

        if body_group_id is None:
            default_group_id = _site_default_group_id(session, src_site_id)
            if default_group_id is None:
                raise HTTPException(
                    status_code=500,
                    detail=f"Site {src_site_id} has no Default group (unexpected)",
                )
            target_group_id = default_group_id
            target_site_id = src_site_id
        else:
            target_group_id = int(body_group_id)
            row = (
                session.query(DeviceGroupModel.site_id)
                .filter(DeviceGroupModel.id == target_group_id)
                .first()
            )
            if row is None or row[0] is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target device_group {target_group_id} does not exist",
                )
            target_site_id = row[0]

    same_site = target_site_id == src_site_id

    if same_site:
        role = scope.rol_para(src_site_id, src_group_id)
        _enforce(
            role, "operator", "move_device_same_site", "device", name,
        )
        dst_role = scope.rol_para(target_site_id, target_group_id)
        _enforce(
            dst_role, "operator", "move_device_same_site", "device_group", target_group_id,
        )
    else:
        src_role = scope.rol_para(src_site_id, src_group_id)
        dst_role = scope.rol_para(target_site_id, None)
        for label, role in (("source", src_role), ("target", dst_role)):
            _enforce(
                role, "admin", "move_device_cross_site",
                "site", target_site_id if label == "target" else src_site_id,
            )


async def _resolve_target(request: Request, scope_kind: str):
    pp = request.path_params
    if scope_kind == "device":
        from_path = pp.get("name") or pp.get("device_name")
        if from_path:
            return from_path
        body = await _peek_json_body(request)
        if isinstance(body, dict):
            if body.get("device"):
                return str(body["device"])
            devices = body.get("devices")
            if isinstance(devices, list) and devices:
                return str(devices[0])
        return None
    if scope_kind == "device_group":
        if "group_id" in pp:
            try:
                return int(pp["group_id"])
            except (TypeError, ValueError):
                return None
        body = await _peek_json_body(request)
        if isinstance(body, dict) and body.get("device_group_id") is not None:
            try:
                return int(body["device_group_id"])
            except (TypeError, ValueError):
                return None
        return None
    if scope_kind == "site":
        if "site_id" in pp:
            try:
                return int(pp["site_id"])
            except (TypeError, ValueError):
                return None
        body = await _peek_json_body(request)
        if isinstance(body, dict):
            if body.get("site_id") is not None:
                try:
                    return int(body["site_id"])
                except (TypeError, ValueError):
                    return None
            if body.get("device_group_id") is not None:
                with get_session() as session:
                    row = (
                        session.query(DeviceGroupModel.site_id)
                        .filter(DeviceGroupModel.id == int(body["device_group_id"]))
                        .first()
                    )
                    return int(row[0]) if row and row[0] is not None else None
        return None
    return None


async def _peek_json_body(request: Request) -> dict:
    if request.method in ("GET", "HEAD", "DELETE"):
        return {}
    body = await request.body()
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolver_site_group(
    target, scope_kind: str,
) -> Optional[Tuple[int, Optional[int]]]:
    if scope_kind == "site":
        try:
            return (int(target), None)
        except (TypeError, ValueError):
            return None
    if scope_kind == "device_group":
        try:
            group_id = int(target)
        except (TypeError, ValueError):
            return None
        with get_session() as session:
            row = (
                session.query(DeviceGroupModel.site_id)
                .filter(DeviceGroupModel.id == group_id)
                .first()
            )
        if row is None or row[0] is None:
            return None
        return (int(row[0]), group_id)
    if scope_kind == "device":
        with get_session() as session:
            return _lookup_device_scope(session, str(target))
    raise ValueError(f"unknown scope_kind: {scope_kind!r}")


def _lookup_device_scope(session, name: str) -> Optional[Tuple[int, Optional[int]]]:
    row = (
        session.query(
            DeviceModel.device_group_id,
            DeviceGroupModel.site_id.label("group_site_id"),
        )
        .join(DeviceGroupModel, DeviceModel.device_group_id == DeviceGroupModel.id)
        .filter(DeviceModel.name == name)
        .first()
    )
    if row is None:
        return None
    group_id, group_site_id = row
    return (int(group_site_id), int(group_id))


def _site_default_group_id(session, site_id: int) -> Optional[int]:
    row = (
        session.query(SiteModel.default_group_id)
        .filter(SiteModel.id == site_id)
        .first()
    )
    return int(row[0]) if row and row[0] is not None else None


def _enforce(role: Optional[str], min_role: str, op: str, scope_kind: str, target) -> None:
    if role is None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"No role assignment for {scope_kind} {target}; "
                f"operation '{op}' requires >= {min_role}"
            ),
        )
    if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL[min_role]:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Role '{role}' on {scope_kind} {target} is below minimum "
                f"'{min_role}' for operation '{op}'"
            ),
        )


def require_device(name: str):
    from app.composition import device_repository

    device = device_repository.get(name)
    if device is None:
        raise NotFoundError(f"Device '{name}' not found")
    return device


def authorize_device(
    scope: VisibilityScope, device_name: str, op: str, min_role: str,
    resolved: "Tuple[int, Optional[int]] | None" = None,
) -> None:
    if resolved is None:
        resolved = resolver_site_group(device_name, "device")
    role = scope.rol_para(*resolved) if resolved is not None else None
    _enforce(role, min_role, op, "device", device_name)


def visible_or_404(
    scope: VisibilityScope, target, kind: str, min_role: str, not_found_message: str,
) -> None:
    resolved = resolver_site_group(target, kind)
    role = scope.rol_para(*resolved) if resolved is not None else None
    if role is None or _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL[min_role]:
        raise NotFoundError(not_found_message)
