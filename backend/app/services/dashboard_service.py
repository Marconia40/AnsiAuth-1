from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_

from app.db.models import (
    DeviceGlobalConfigModel,
    DeviceGroupModel,
    DeviceModel,
    DevicePortModel,
    DeviceSVIModel,
    DeviceVlanModel,
    JobModel,
)
from app.db.session import get_session
from app.models.visibility_scope import VisibilityScope


def build_global_config_payload(device: str, vendor: "str | None", config) -> dict:
    from app.schemas.global_config import (
        GlobalConfigDnsInfo,
        GlobalConfigLoggingInfo,
        GlobalConfigNtpInfo,
        GlobalConfigRead,
        GlobalConfigSnmpInfo,
    )

    return {
        "device": device,
        "vendor": vendor,
        **GlobalConfigRead(
            hostname=config.hostname if config else None,
            snmp=GlobalConfigSnmpInfo(
                enabled=config.snmp_enabled if config else None,
                version=config.snmp_version if config else None,
                community=config.snmp_community if config else None,
                permission=config.snmp_permission if config else None,
                trap_hosts=config.snmp_trap_hosts if config else None,
            ),
            ntp=GlobalConfigNtpInfo(servers=config.ntp_servers if config else None),
            dns=GlobalConfigDnsInfo(servers=config.dns_servers if config else None),
            logging=GlobalConfigLoggingInfo(
                servers=config.log_servers if config else None,
                level=config.log_level if config else None,
            ),
            routes=config.routes if config else None,
            acls=config.acls if config else None,
        ).model_dump(),
    }


class DashboardService:
    def __init__(self, redis_coordinator):
        self._coordinator = redis_coordinator


    def resumir(
        self,
        *,
        scope_kind: str,
        scope_id: Optional[int],
        device_name: Optional[str],
        jobs_days: int,
        visibility_scope: VisibilityScope,
        include_global_config: bool = False,
    ) -> dict:
        resuelto = self.resolver_devices_del_scope(
            scope_kind, scope_id, device_name, visibility_scope,
        )
        if resuelto is None:
            return None
        device_names, scope_display_name = resuelto

        devices = self._resumen_devices(device_names)
        vlans = self._resumen_vlans(device_names)
        ports = self._resumen_ports(device_names)
        svis = self._resumen_svis(device_names)
        jobs = self._resumen_jobs(device_names, jobs_days, visibility_scope)

        payload = {
            "scope": {
                "kind": scope_kind,
                "id": scope_id,
                "name": scope_display_name,
            },
            "generated_at": datetime.now(timezone.utc),
            "devices": devices,
            "vlans": vlans,
            "ports": ports,
            "svis": svis,
            "jobs": jobs,
        }
        if include_global_config:
            payload["global_config"] = self._resumen_global_config(device_names)
        return payload


    def resolver_devices_del_scope(
        self,
        scope_kind: str,
        scope_id: Optional[int],
        device_name: Optional[str],
        visibility_scope: VisibilityScope,
    ) -> Optional[tuple[set[str], Optional[str]]]:
        from app.composition import (
            device_group_repository,
            device_repository,
            site_repository,
        )

        visibles = device_repository.nombres_visibles(visibility_scope)

        if scope_kind == "org":
            return self._names_org(visibles), None

        if scope_kind == "site":
            site = site_repository.get(scope_id)
            if site is None:
                return None
            names = self._names_por_site(scope_id, visibles)
            return names, site.name

        if scope_kind == "group":
            group = device_group_repository.get(scope_id)
            if group is None:
                return None
            names = self._names_por_grupo(scope_id, visibles)
            return names, group.name

        if scope_kind == "device":
            dev = device_repository.get(device_name)
            if dev is None:
                return None
            if visibles is None or device_name in visibles:
                return {device_name}, device_name
            return set(), device_name

        raise ValueError(f"Scope kind inválido: {scope_kind!r}")

    def _names_org(self, visibles: Optional[set[str]]) -> set[str]:
        if visibles is not None:
            return visibles
        with get_session() as session:
            return {r[0] for r in session.query(DeviceModel.name).all()}

    def _names_por_site(
        self, site_id: int, visibles: Optional[set[str]],
    ) -> set[str]:
        with get_session() as session:
            q = (
                session.query(DeviceModel.name)
                .join(
                    DeviceGroupModel,
                    DeviceModel.device_group_id == DeviceGroupModel.id,
                )
                .filter(DeviceGroupModel.site_id == site_id)
            )
            names_en_site = {r[0] for r in q.all()}
        if visibles is None:
            return names_en_site
        return names_en_site & visibles

    def _names_por_grupo(
        self, group_id: int, visibles: Optional[set[str]],
    ) -> set[str]:
        with get_session() as session:
            q = session.query(DeviceModel.name).filter(
                DeviceModel.device_group_id == group_id,
            )
            names_en_grupo = {r[0] for r in q.all()}
        if visibles is None:
            return names_en_grupo
        return names_en_grupo & visibles


    def _resumen_devices(self, device_names: set[str]) -> dict:
        if not device_names:
            return {
                "total": 0,
                "by_vendor": {},
                "sync_errors": 0,
                "last_sync_at": None,
                "sync_in_progress_count": 0,
            }

        with get_session() as session:
            rows = (
                session.query(DeviceModel.vendor, func.count(DeviceModel.id))
                .filter(DeviceModel.name.in_(device_names))
                .group_by(DeviceModel.vendor)
                .all()
            )
            by_vendor = {vendor: count for vendor, count in rows}
            total = sum(by_vendor.values())

            sync_error_count = (
                session.query(func.count(DeviceModel.id))
                .filter(DeviceModel.name.in_(device_names))
                .filter(
                    or_(
                        DeviceModel.vlans_sync_error.isnot(None),
                        DeviceModel.ports_sync_error.isnot(None),
                        DeviceModel.svis_sync_error.isnot(None),
                    )
                )
                .scalar() or 0
            )

            last_sync = (
                session.query(
                    func.min(
                        func.coalesce(
                            DeviceModel.vlans_synced_at,
                            DeviceModel.ports_synced_at,
                            DeviceModel.svis_synced_at,
                        )
                    )
                )
                .filter(DeviceModel.name.in_(device_names))
                .scalar()
            )

        in_progress = sum(
            1 for name in device_names if self._coordinator.esta_ocupado(name)
        )

        return {
            "total": total,
            "by_vendor": by_vendor,
            "sync_errors": int(sync_error_count),
            "last_sync_at": last_sync,
            "sync_in_progress_count": in_progress,
        }

    def _resumen_vlans(self, device_names: set[str]) -> dict:
        if not device_names:
            return {"unique_count": 0, "entries": []}

        with get_session() as session:
            rows = (
                session.query(DeviceVlanModel.vlan_id, DeviceVlanModel.name)
                .filter(DeviceVlanModel.device.in_(device_names))
                .all()
            )

        names_por_id: dict[int, set[str]] = {}
        for vlan_id, name in rows:
            names_por_id.setdefault(vlan_id, set()).add(name)

        entries = [
            {"id": vlan_id, "names": sorted(names)}
            for vlan_id, names in sorted(names_por_id.items())
        ]
        return {"unique_count": len(entries), "entries": entries}

    def _resumen_ports(self, device_names: set[str]) -> dict:
        if not device_names:
            return {"total": 0, "up": 0, "down": 0, "shutdown": 0}

        with get_session() as session:
            total = (
                session.query(func.count(DevicePortModel.interface))
                .filter(DevicePortModel.device.in_(device_names))
                .scalar() or 0
            )
            shutdown = (
                session.query(func.count(DevicePortModel.interface))
                .filter(DevicePortModel.device.in_(device_names))
                .filter(DevicePortModel.admin_up.is_(False))
                .scalar() or 0
            )
            up = (
                session.query(func.count(DevicePortModel.interface))
                .filter(DevicePortModel.device.in_(device_names))
                .filter(DevicePortModel.admin_up.isnot(False))
                .filter(DevicePortModel.operational_up.is_(True))
                .scalar() or 0
            )
            down = (
                session.query(func.count(DevicePortModel.interface))
                .filter(DevicePortModel.device.in_(device_names))
                .filter(DevicePortModel.admin_up.isnot(False))
                .filter(DevicePortModel.operational_up.is_(False))
                .scalar() or 0
            )
        return {
            "total": int(total),
            "up": int(up),
            "down": int(down),
            "shutdown": int(shutdown),
        }

    def _resumen_svis(self, device_names: set[str]) -> dict:
        if not device_names:
            return {"total": 0, "up": 0, "down": 0, "shutdown": 0}

        with get_session() as session:
            total = (
                session.query(func.count(DeviceSVIModel.vlan_id))
                .filter(DeviceSVIModel.device.in_(device_names))
                .scalar() or 0
            )
            shutdown = (
                session.query(func.count(DeviceSVIModel.vlan_id))
                .filter(DeviceSVIModel.device.in_(device_names))
                .filter(DeviceSVIModel.admin_up.is_(False))
                .scalar() or 0
            )
            up = (
                session.query(func.count(DeviceSVIModel.vlan_id))
                .filter(DeviceSVIModel.device.in_(device_names))
                .filter(DeviceSVIModel.admin_up.isnot(False))
                .filter(DeviceSVIModel.operational_up.is_(True))
                .scalar() or 0
            )
            down = (
                session.query(func.count(DeviceSVIModel.vlan_id))
                .filter(DeviceSVIModel.device.in_(device_names))
                .filter(DeviceSVIModel.admin_up.isnot(False))
                .filter(DeviceSVIModel.operational_up.is_(False))
                .scalar() or 0
            )
        return {
            "total": int(total),
            "up": int(up),
            "down": int(down),
            "shutdown": int(shutdown),
        }

    def _resumen_jobs(
        self,
        device_names: set[str],
        jobs_days: int,
        visibility_scope: VisibilityScope,
    ) -> dict:
        window_days = jobs_days
        from_date = datetime.now(timezone.utc) - timedelta(days=window_days)

        if not device_names:
            return {
                "window_days": window_days,
                "total": 0,
                "by_status": {},
                "rollback_performed_count": 0,
            }

        with get_session() as session:
            base_filter = and_(
                JobModel.created_at >= from_date,
                JobModel.device.in_(device_names),
            )

            rows = (
                session.query(JobModel.status, func.count(JobModel.id))
                .filter(base_filter)
                .group_by(JobModel.status)
                .all()
            )
            by_status = {status: count for status, count in rows}
            total = sum(by_status.values())

            rollback_count = (
                session.query(func.count(JobModel.id))
                .filter(base_filter)
                .filter(JobModel.rollback_performed.is_(True))
                .scalar() or 0
            )

        return {
            "window_days": window_days,
            "total": total,
            "by_status": by_status,
            "rollback_performed_count": int(rollback_count),
        }

    def _resumen_global_config(self, device_names: set[str]) -> list[dict]:
        if not device_names:
            return []

        with get_session() as session:
            config_rows = (
                session.query(
                    DeviceGlobalConfigModel.device,
                    DeviceGlobalConfigModel.hostname,
                    DeviceGlobalConfigModel.snmp_enabled,
                    DeviceGlobalConfigModel.snmp_version,
                    DeviceGlobalConfigModel.snmp_community,
                    DeviceGlobalConfigModel.snmp_permission,
                    DeviceGlobalConfigModel.snmp_trap_hosts,
                    DeviceGlobalConfigModel.ntp_servers,
                    DeviceGlobalConfigModel.dns_servers,
                    DeviceGlobalConfigModel.log_servers,
                    DeviceGlobalConfigModel.log_level,
                    DeviceGlobalConfigModel.routes,
                    DeviceGlobalConfigModel.acls,
                )
                .filter(DeviceGlobalConfigModel.device.in_(device_names))
                .all()
            )
            meta_rows = (
                session.query(
                    DeviceModel.name,
                    DeviceModel.vendor,
                    DeviceModel.global_config_synced_at,
                    DeviceModel.global_config_sync_error,
                )
                .filter(DeviceModel.name.in_(device_names))
                .all()
            )

        configs_by_device = {row.device: row for row in config_rows}

        entries = []
        for name, vendor, synced_at, sync_error in meta_rows:
            entry = build_global_config_payload(name, vendor, configs_by_device.get(name))
            entry["synced_at"] = synced_at
            entry["sync_error"] = sync_error
            entry["sync_in_progress"] = self._coordinator.esta_ocupado(name)
            entries.append(entry)
        return sorted(entries, key=lambda e: e["device"])
