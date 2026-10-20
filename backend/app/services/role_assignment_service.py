from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from app.db.models import (
    DeviceGroupModel,
    RoleAssignmentModel,
    SiteModel,
    UserModel,
)
from app.db.session import get_session
from app.models.domain_event import DomainEvent
from app.repositories.role_assignment_repository import RoleAssignment
from app.schemas.role_assignment import _VALID_ASSIGNMENT_ROLES, RoleAssignmentRead

logger = logging.getLogger(__name__)


def _to_read(row: RoleAssignmentModel) -> RoleAssignmentRead:
    return RoleAssignmentRead(
        id=row.id,
        user_id=row.user_id,
        site_id=row.site_id,
        site_name=row.site.name if row.site is not None else None,
        device_group_id=row.device_group_id,
        device_group_name=(
            row.device_group.name if row.device_group is not None else None
        ),
        role=row.role,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
        created_by_username=(
            row.created_by.username if row.created_by is not None else None
        ),
    )


def _leer(grant_id: int) -> RoleAssignmentRead:
    with get_session() as session:
        row = session.query(RoleAssignmentModel).filter_by(id=grant_id).first()
        return _to_read(row)


class RoleAssignmentService:
    def __init__(self, db=None):
        self._db = db


    def grant(
        self,
        *,
        target_user_id: int,
        site_id: int,
        device_group_id: Optional[int],
        role: str,
        actor: dict,
    ) -> RoleAssignmentRead:
        if role not in _VALID_ASSIGNMENT_ROLES:
            raise ValueError(
                f"role must be one of {sorted(_VALID_ASSIGNMENT_ROLES)}"
            )
        with get_session() as session:
            target_user = session.query(UserModel).filter_by(id=target_user_id).first()
            if target_user is None:
                raise HTTPException(status_code=404, detail=f"User {target_user_id} not found")
            site = session.query(SiteModel).filter_by(id=site_id).first()
            if site is None:
                raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
            if device_group_id is not None:
                group = (
                    session.query(DeviceGroupModel)
                    .filter_by(id=device_group_id)
                    .first()
                )
                if group is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Device group {device_group_id} not found",
                    )
                if group.site_id != site_id:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Device group {device_group_id} belongs to site "
                            f"{group.site_id}, not site {site_id}"
                        ),
                    )
        self._authorize_grant_or_revoke(
            actor=actor, site_id=site_id,
            device_group_id=device_group_id, role_being_granted=role,
        )
        from app.composition import event_dispatcher, role_assignment_repository

        actor_username = (actor.get("username") if actor else None) or "system"
        existentes = role_assignment_repository.list(
            user_id=target_user_id, site_id=site_id, device_group_id=device_group_id,
        )
        existing = existentes[0] if existentes else None
        if existing is not None:
            noop = existing.role == role
            if not noop:
                existing.role = role
                role_assignment_repository.add(existing)
            record = _leer(existing.id)
            event_dispatcher.despachar([DomainEvent(
                "update_role_assignment", existing, None, actor_username,
                {
                    "resource_id": existing.id,
                    "user_id": target_user_id, "site_id": site_id,
                    "device_group_id": device_group_id, "role": role,
                    "noop": noop,
                },
            )])
            return record
        nuevo = RoleAssignment(
            user_id=target_user_id, site_id=site_id, device_group_id=device_group_id,
            role=role, created_by_user_id=actor.get("id") if actor else None,
        )
        creado = role_assignment_repository.add(nuevo)
        record = _leer(creado.id)
        event_dispatcher.despachar([DomainEvent(
            "grant_role_assignment", creado, None, actor_username,
            {
                "resource_id": creado.id,
                "target_user_id": target_user_id,
                "site_id": site_id,
                "device_group_id": device_group_id,
                "role": role,
            },
        )])
        return record

    def revoke(self, grant_id: int, actor: dict) -> None:
        from app.composition import event_dispatcher, role_assignment_repository

        existing = role_assignment_repository.get(grant_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Grant {grant_id} not found")
        self._authorize_grant_or_revoke(
            actor=actor, site_id=existing.site_id,
            device_group_id=existing.device_group_id,
            role_being_granted=existing.role,
        )
        details = {
            "resource_id": grant_id,
            "grant_id": grant_id,
            "user_id": existing.user_id,
            "site_id": existing.site_id,
            "device_group_id": existing.device_group_id,
            "role": existing.role,
        }
        role_assignment_repository.remove(grant_id)
        actor_username = (actor.get("username") if actor else None) or "system"
        event_dispatcher.despachar([DomainEvent(
            "revoke_role_assignment", existing, None, actor_username, details,
        )])

    def list_for_user(
        self,
        user_id: int,
        viewer: dict,
    ) -> list[RoleAssignmentRead]:
        with get_session() as session:
            if not session.query(UserModel.id).filter_by(id=user_id).first():
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            q = session.query(RoleAssignmentModel).filter_by(user_id=user_id)
            rows = q.all()
            if viewer.get("is_system_admin") or viewer.get("id") == user_id:
                return [_to_read(r) for r in rows]
            viewer_id = viewer.get("id")
            if viewer_id is None:
                return []
            admin_grants = (
                session.query(
                    RoleAssignmentModel.site_id,
                    RoleAssignmentModel.device_group_id,
                )
                .filter(
                    RoleAssignmentModel.user_id == viewer_id,
                    RoleAssignmentModel.role == "admin",
                )
                .all()
            )
            visible_sites = {sid for (sid, gid) in admin_grants if gid is None}
            visible_groups = {gid for (_sid, gid) in admin_grants if gid is not None}
            filtered = [
                r for r in rows
                if r.site_id in visible_sites
                or (r.device_group_id is not None and r.device_group_id in visible_groups)
            ]
            return [_to_read(r) for r in filtered]

    def set_system_admin(
        self,
        target_user_id: int,
        is_system_admin: bool,
        actor: dict,
    ) -> None:
        if not actor.get("is_system_admin"):
            raise HTTPException(
                status_code=403,
                detail="Only system-admins may modify the system-admin flag",
            )
        with get_session() as session:
            row = session.query(UserModel).filter_by(id=target_user_id).first()
            if row is None:
                raise HTTPException(status_code=404, detail=f"User {target_user_id} not found")
            if not is_system_admin and row.is_system_admin:
                remaining = (
                    session.query(UserModel)
                    .filter(
                        UserModel.is_system_admin.is_(True),
                        UserModel.is_active.is_(True),
                        UserModel.id != target_user_id,
                    )
                    .count()
                )
                if remaining == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Cannot demote the last active system-admin — "
                            "promote another user first"
                        ),
                    )
            row.is_system_admin = bool(is_system_admin)
        from app.composition import event_dispatcher, user_repository

        target_user = user_repository.get(target_user_id)
        event_dispatcher.despachar([DomainEvent(
            "set_system_admin", target_user, None,
            (actor.get("username") if actor else None) or "system",
            {"resource_id": target_user_id, "is_system_admin": is_system_admin},
        )])


    def _authorize_grant_or_revoke(
        self,
        *,
        actor: dict,
        site_id: int,
        device_group_id: Optional[int],
        role_being_granted: str,
    ) -> None:
        if actor.get("is_system_admin"):
            return
        actor_id = actor.get("id")
        if actor_id is None:
            raise HTTPException(
                status_code=403,
                detail="Grant operations require a fully-authenticated actor",
            )
        from app.composition import role_assignment_repository

        scope = role_assignment_repository.scope_de(actor)
        if scope.rol_para(site_id, None) == "admin":
            return
        raise HTTPException(
            status_code=403,
            detail=(
                "Grant operations require system-admin or a site-wide admin "
                f"grant on site {site_id} (group-admins may not delegate — D25)"
            ),
        )
