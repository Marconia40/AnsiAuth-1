from __future__ import annotations

from datetime import datetime, timezone

from app.core.repository import Repository
from app.db.models import DeviceGroupModel, DeviceModel
from app.db.session import get_session
from app.models.device import Device
from app.models.visibility_scope import VisibilityScope


def _to_domain(row: DeviceModel) -> Device:
    group = getattr(row, "device_group", None)
    group_id = group.id if group is not None else None
    group_name = group.name if group is not None else None
    site_id = group.site_id if group is not None else None
    site_name = group.site.name if group is not None and group.site is not None else None
    return Device(
        name=row.name,
        host=row.host,
        vendor=row.vendor,
        platform=row.platform or "ios",
        username=row.username,
        encrypted_password=row.encrypted_password,
        auth_method=row.auth_method or "password",
        encrypted_private_key=row.encrypted_private_key,
        id=str(row.id),
        created_at=row.created_at or datetime.now(timezone.utc),
        site_id=site_id,
        site_name=site_name,
        device_group_id=group_id,
        device_group_name=group_name,
    )


def _to_orm(d: Device) -> DeviceModel:
    return DeviceModel(
        name=d.name,
        host=d.host,
        vendor=d.vendor,
        platform=d.platform,
        username=d.username,
        encrypted_password=d.encrypted_password,
        auth_method=d.auth_method,
        encrypted_private_key=d.encrypted_private_key,
        device_group_id=d.device_group_id,
    )


class DeviceRepository(Repository):
    def __init__(self):
        super().__init__(DeviceModel, _to_domain, _to_orm, pk_field="name")

    def nombres_visibles(self, scope: VisibilityScope) -> "set[str] | None":
        if scope.es_system_admin:
            return None
        if not scope.site_ids and not scope.device_group_ids:
            return set()
        from sqlalchemy import or_

        with get_session() as session:
            q = session.query(DeviceModel.name).join(
                DeviceGroupModel, DeviceModel.device_group_id == DeviceGroupModel.id,
            )
            conds = []
            if scope.site_ids:
                conds.append(DeviceGroupModel.site_id.in_(scope.site_ids))
            if scope.device_group_ids:
                conds.append(DeviceModel.device_group_id.in_(scope.device_group_ids))
            return {r[0] for r in q.filter(or_(*conds)).all()}
