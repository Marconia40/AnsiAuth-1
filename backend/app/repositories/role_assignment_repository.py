from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.repository import Repository
from app.db.models import RoleAssignmentModel
from app.db.session import get_session
from app.models.visibility_scope import VisibilityScope


@dataclass
class RoleAssignment:
    user_id: int
    site_id: int
    role: str
    device_group_id: "int | None" = None
    id: "int | None" = None
    created_by_user_id: "int | None" = None
    created_at: "datetime | None" = None

    def repositorio(self) -> str:
        return "role_assignment"


def _to_domain(row: RoleAssignmentModel) -> RoleAssignment:
    return RoleAssignment(
        id=row.id,
        user_id=row.user_id,
        site_id=row.site_id,
        device_group_id=row.device_group_id,
        role=row.role,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


def _to_orm(ra: RoleAssignment) -> RoleAssignmentModel:
    row = RoleAssignmentModel(
        id=ra.id,
        user_id=ra.user_id,
        site_id=ra.site_id,
        device_group_id=ra.device_group_id,
        role=ra.role,
        created_by_user_id=ra.created_by_user_id,
    )
    if ra.created_at is not None:
        row.created_at = ra.created_at
    return row


class RoleAssignmentRepository(Repository):
    def __init__(self):
        super().__init__(RoleAssignmentModel, _to_domain, _to_orm)

    def scope_de(self, user: dict) -> VisibilityScope:
        if user.get("is_system_admin"):
            return VisibilityScope(es_system_admin=True, grants=())
        user_id = user.get("id")
        if user_id is None:
            return VisibilityScope(es_system_admin=False, grants=())
        with get_session() as session:
            rows = (
                session.query(
                    RoleAssignmentModel.site_id,
                    RoleAssignmentModel.device_group_id,
                    RoleAssignmentModel.role,
                )
                .filter(RoleAssignmentModel.user_id == user_id)
                .all()
            )
        return VisibilityScope(
            es_system_admin=False,
            grants=tuple((r.site_id, r.device_group_id, r.role) for r in rows),
        )
