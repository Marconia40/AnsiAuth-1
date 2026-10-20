from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException

from app.core.exceptions import ValidationError
from app.db.models import DeviceGroupModel, DeviceModel, SiteModel
from app.db.session import get_session
from app.models.device import Device
from app.models.domain_event import DomainEvent

if TYPE_CHECKING:
    from app.models.visibility_scope import VisibilityScope

logger = logging.getLogger(__name__)


class Inventory:
    def __init__(self, devices, sites, device_groups, role_assignments, jobs, auditor, vault):
        self._devices = devices
        self._sites = sites
        self._device_groups = device_groups
        self._role_assignments = role_assignments
        self._jobs = jobs
        self._auditor = auditor
        self._vault = vault


    def get(self, name: str) -> Optional[Device]:
        return self._devices.get(name)

    def list(
        self,
        scope: "VisibilityScope",
        *,
        site_id: Optional[int] = None,
        device_group_id: Optional[int] = None,
    ) -> list[Device]:
        nombres = self._devices.nombres_visibles(scope)
        if nombres is None:
            devices = self._devices.list()
        elif not nombres:
            return []
        else:
            devices = [d for d in self._devices.list() if d.name in nombres]
        if site_id is not None:
            devices = [d for d in devices if d.site_id == site_id]
        if device_group_id is not None:
            devices = [d for d in devices if d.device_group_id == device_group_id]
        return devices


    def register(
        self,
        *,
        name: str,
        host: str,
        vendor: str,
        platform: str,
        username: str,
        password: "str | None" = None,
        auth_method: str = "password",
        private_key: "str | None" = None,
        site_id: int,
        device_group_id: Optional[int],
        actor: dict,
    ) -> Device:
        site = self._sites.get(site_id)
        if site is None:
            raise ValidationError(f"site {site_id} no existe")
        if self._devices.get(name) is not None:
            raise ValidationError(f"Device '{name}' already exists")
        group = (
            self._device_groups.get(device_group_id)
            if device_group_id
            else self._sites.grupo_default(site)
        )
        if group is None:
            raise ValidationError(f"Device group {device_group_id} not found")
        if group.site_id != site_id:
            raise ValidationError(
                f"Device group {group.id} belongs to site {group.site_id}, not site {site_id}"
            )
        encrypted = self._vault.encrypt(password if auth_method == "password" else "")
        encrypted_private_key = (
            self._vault.encrypt(private_key) if auth_method == "key" else None
        )
        device = Device.nuevo(
            name, host, vendor, platform, username, encrypted, group.id,
            auth_method=auth_method, encrypted_private_key=encrypted_private_key,
        )
        device = self._devices.add(device)
        self._auditor.despachar([DomainEvent(
            "device_registrado", device, device, actor["username"], {"site_id": site_id},
        )])
        try:
            from app.tasks import sync_device_task
            sync_device_task.delay(device.name, "all")
        except Exception as exc:
            logger.warning(
                "Inventory.register: sync task enqueue failed for %s (%s) — "
                "device registered without initial sync; refresh manually",
                device.name, exc,
            )
        logger.info("Inventory.register: %s → group=%s site=%s", name, group.id, site_id)
        return device

    def move(
        self,
        name: str,
        target_group_id: Optional[int],
        actor: dict,
        *,
        reason: Optional[str] = None,
        enforce_authz: bool = True,
    ) -> Device:
        with get_session() as session:
            row = session.query(DeviceModel).filter_by(name=name).first()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Device '{name}' not found")

            source_group = row.device_group
            source_group_id = source_group.id if source_group is not None else None
            source_site_id = source_group.site_id if source_group is not None else None
            if source_site_id is None:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Device '{name}' is not attached to a group; refusing "
                        "to move — data-integrity invariant violated"
                    ),
                )

            if target_group_id is None:
                default_group_id = (
                    session.query(SiteModel.default_group_id)
                    .filter(SiteModel.id == source_site_id)
                    .scalar()
                )
                if default_group_id is None:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Site {source_site_id} has no Default group",
                    )
                resolved_group_id = int(default_group_id)
            else:
                resolved_group_id = int(target_group_id)

            target_group = (
                session.query(DeviceGroupModel).filter_by(id=resolved_group_id).first()
            )
            if target_group is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target device group {resolved_group_id} does not exist",
                )
            if target_group.site_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Target device group {resolved_group_id} is not attached to a site"
                    ),
                )
            target_site_id = int(target_group.site_id)

            noop = source_group_id == resolved_group_id
            if not noop:
                if self._jobs.activo_para(name):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Cannot move device '{name}': a job is currently pending/running. "
                            "Wait for it to finish or cancel it."
                        ),
                    )
                row.device_group_id = resolved_group_id
                session.flush()

        device = self._devices.get(name)
        self._auditor.despachar([DomainEvent(
            "device_movido", device, device, actor["username"],
            {
                "name": name,
                "from_group_id": source_group_id,
                "from_site_id": source_site_id,
                "to_group_id": resolved_group_id,
                "to_site_id": target_site_id,
                "cross_site": source_site_id != target_site_id,
                "reason": reason,
                "resolved_from_default": target_group_id is None,
                "noop": noop,
            },
        )])
        logger.info(
            "Inventory.move: %s → group=%s (site=%s, cross_site=%s, reason=%s, noop=%s)",
            name, resolved_group_id, target_site_id,
            source_site_id != target_site_id, reason, noop,
        )
        return device

    def deregister(self, name: str, actor: dict) -> None:
        device = self._devices.get(name)
        if device is None:
            raise HTTPException(status_code=404, detail=f"Device '{name}' not found")
        if self._jobs.activo_para(name):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete device '{name}': a job is currently pending/running.",
            )
        with get_session() as session:
            session.query(DeviceModel).filter_by(name=name).delete()
        self._auditor.despachar([DomainEvent(
            "device_dado_de_baja", device, device, actor["username"], {"name": name},
        )])
        logger.info("Inventory.deregister: %s", name)
