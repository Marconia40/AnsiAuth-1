from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.core.exceptions import SiteHasDevicesError
from app.core.repository import Repository
from app.db.models import DeviceGroupModel, DeviceModel, SiteModel
from app.db.session import get_session
from app.models.site import Site

if TYPE_CHECKING:
    from app.models.device_group import DeviceGroup
    from app.models.visibility_scope import VisibilityScope

DEFAULT_GROUP_NAME = "Default"
BASE_INFRA_SITE_KIND = "BASE_INFRASTRUCTURE"


def _to_domain(row: SiteModel) -> Site:
    return Site(
        id=row.id,
        name=row.name,
        description=row.description,
        kind=row.kind,
        default_group_id=row.default_group_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_orm(s: Site) -> SiteModel:
    return SiteModel(
        id=s.id, name=s.name, description=s.description, kind=s.kind,
        default_group_id=s.default_group_id,
    )


def _default_group_name_for_site(session, site_id: int) -> str:
    existing = (
        session.query(DeviceGroupModel)
        .filter_by(name=DEFAULT_GROUP_NAME, site_id=site_id)
        .first()
    )
    if existing is None:
        return DEFAULT_GROUP_NAME
    return f"{DEFAULT_GROUP_NAME} (site {site_id})"


class SiteRepository(Repository):
    def __init__(self):
        super().__init__(SiteModel, _to_domain, _to_orm)

    def crear_con_grupo_default(
        self, name: str, description: Optional[str] = None, *, kind: str = "REGULAR",
    ) -> Site:
        with get_session() as session:
            if kind == BASE_INFRA_SITE_KIND:
                existente = session.query(SiteModel).filter_by(kind=kind).first()
                if existente is not None:
                    return self._asegurar_grupo_default(session, existente)
            elif session.query(SiteModel).filter_by(name=name).first():
                raise ValueError(f"Site '{name}' already exists")
            row = SiteModel(name=name, description=description, kind=kind)
            session.add(row)
            session.flush()
            grupo = DeviceGroupModel(
                name=_default_group_name_for_site(session, row.id),
                site_id=row.id,
                is_default=True,
                description=f"Default group for site '{name}'.",
            )
            session.add(grupo)
            session.flush()
            row.default_group_id = grupo.id
            session.flush()
            return _to_domain(row)

    def _asegurar_grupo_default(self, session, row: SiteModel) -> Site:
        if row.default_group_id is None:
            existing_default = (
                session.query(DeviceGroupModel)
                .filter_by(site_id=row.id, is_default=True)
                .first()
            )
            if existing_default is None:
                group = DeviceGroupModel(
                    name=DEFAULT_GROUP_NAME, site_id=row.id, is_default=True,
                    description=f"Default group for {row.name}.",
                )
                session.add(group)
                session.flush()
                row.default_group_id = group.id
            else:
                row.default_group_id = existing_default.id
            session.flush()
        return _to_domain(row)

    def grupo_default(self, site: Site) -> "DeviceGroup":
        from app.models.device_group import DeviceGroup

        if site.default_group_id is None:
            raise ValueError(f"Site {site.id} has no Default group")
        with get_session() as session:
            row = (
                session.query(DeviceGroupModel)
                .filter_by(id=site.default_group_id)
                .first()
            )
            if row is None:
                raise ValueError(
                    f"Site {site.id}'s Default group {site.default_group_id} not found"
                )
            return DeviceGroup(
                id=row.id, name=row.name, description=row.description,
                site_id=row.site_id, es_default=row.is_default, created_at=row.created_at,
            )

    def visibles(self, scope: "VisibilityScope") -> list[Site]:
        with get_session() as session:
            q = session.query(SiteModel)
            if not scope.es_system_admin:
                granted_site_ids = {sid for sid, _gid, _role in scope.grants}
                if not granted_site_ids:
                    return []
                q = q.filter(SiteModel.id.in_(granted_site_ids))
                q = q.filter(SiteModel.kind != BASE_INFRA_SITE_KIND)
            rows = q.order_by(SiteModel.name).all()
            return [_to_domain(r) for r in rows]

    def contar_devices(self, site_id: int) -> int:
        with get_session() as session:
            return (
                session.query(DeviceModel)
                .join(DeviceGroupModel, DeviceModel.device_group_id == DeviceGroupModel.id)
                .filter(DeviceGroupModel.site_id == site_id)
                .count()
            )

    def tiene_devices(self, site_id: int) -> bool:
        return self.contar_devices(site_id) > 0

    def contar_devices_batch(self, site_ids: list[int]) -> dict[int, int]:
        from sqlalchemy import func

        if not site_ids:
            return {}
        with get_session() as session:
            rows = (
                session.query(DeviceGroupModel.site_id, func.count(DeviceModel.id))
                .join(DeviceModel, DeviceModel.device_group_id == DeviceGroupModel.id)
                .filter(DeviceGroupModel.site_id.in_(site_ids))
                .group_by(DeviceGroupModel.site_id)
                .all()
            )
            return {site_id: count for site_id, count in rows}

    def nombres_por_id(self, site_ids: list[int]) -> dict[int, str]:
        if not site_ids:
            return {}
        with get_session() as session:
            rows = (
                session.query(SiteModel.id, SiteModel.name)
                .filter(SiteModel.id.in_(site_ids))
                .all()
            )
            return {site_id: name for site_id, name in rows}

    def eliminar(self, site_id: int) -> bool:
        with get_session() as session:
            row = session.query(SiteModel).filter_by(id=site_id).first()
            if not row:
                return False
            if row.kind == BASE_INFRA_SITE_KIND:
                raise ValueError(
                    "The Base-Infrastructure site is system-managed and cannot be deleted"
                )
            device_count = self.contar_devices(site_id)
            if device_count > 0:
                raise SiteHasDevicesError(site_id, device_count)
            row.default_group_id = None
            session.flush()
            session.query(DeviceGroupModel).filter_by(site_id=site_id).delete(
                synchronize_session=False
            )
            session.flush()
            session.delete(row)
        return True
