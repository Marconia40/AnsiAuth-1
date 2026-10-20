from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import update

from app.db.models import DeviceModel
from app.db.session import get_session

if TYPE_CHECKING:
    from app.models.device import Device

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT_S = 30.0
_MAX_ERROR_LEN = 2000


class DeviceSyncService:
    def __init__(self, vlan_repo, puerto_repo, svi_repo, global_config_repo, coordinator, arp_mac_repo, device_logs_repo):
        self._vlans = vlan_repo
        self._ports = puerto_repo
        self._interfaces = svi_repo
        self._global_config = global_config_repo
        self._coordinator = coordinator
        self._arp_mac = arp_mac_repo
        self._device_logs = device_logs_repo

    def sync_vlans(self, device: "Device") -> None:
        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                nuevos = device.driver.get_vlans(device, device.password)
        except Exception as exc:
            logger.exception("sync_vlans failed device=%s", device.name)
            self._marcar_error(device.name, "vlans_sync_error", str(exc))
            raise

        removed = self._persistir_vlans(device.name, nuevos)

        self._marcar_ok(device.name, "vlans_synced_at", "vlans_sync_error")
        logger.info(
            "sync_vlans OK device=%s persisted=%d removed=%d",
            device.name, len(nuevos), removed,
        )

    def sync_ports(self, device: "Device") -> None:
        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                nuevos = device.driver.list_ports(device, device.password)
        except Exception as exc:
            logger.exception("sync_ports failed device=%s", device.name)
            self._marcar_error(device.name, "ports_sync_error", str(exc))
            raise

        removed = self._persistir_ports(device.name, nuevos)

        self._marcar_ok(device.name, "ports_synced_at", "ports_sync_error")
        logger.info(
            "sync_ports OK device=%s persisted=%d removed=%d",
            device.name, len(nuevos), removed,
        )

    def sync_core(self, device: "Device") -> None:
        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                vlans, ports, svis = device.driver.read_core_state(device, device.password)
        except Exception as exc:
            logger.exception("sync_core read failed device=%s", device.name)
            msg = str(exc)
            self._marcar_error(device.name, "vlans_sync_error", msg)
            self._marcar_error(device.name, "ports_sync_error", msg)
            self._marcar_error(device.name, "svis_sync_error", msg)
            raise

        errores: list[str] = []
        for nombre, err_field, ts_field, persist_fn in (
            ("vlans", "vlans_sync_error", "vlans_synced_at",
             lambda: self._persistir_vlans(device.name, vlans)),
            ("ports", "ports_sync_error", "ports_synced_at",
             lambda: self._persistir_ports(device.name, ports)),
            ("svis", "svis_sync_error", "svis_synced_at",
             lambda: self._persistir_svis(device.name, svis)),
        ):
            try:
                persist_fn()
                self._marcar_ok(device.name, ts_field, err_field)
            except Exception as exc:
                logger.exception("sync_core %s persist failed device=%s", nombre, device.name)
                self._marcar_error(device.name, err_field, str(exc))
                errores.append(f"{nombre}: {exc}")

        if errores:
            raise RuntimeError(
                f"sync_core device={device.name} partial failure: " + "; ".join(errores)
            )

        logger.info(
            "sync_core OK device=%s vlans=%d ports=%d svis=%d",
            device.name, len(vlans), len(ports), len(svis),
        )


    def _persistir_vlans(self, device_name: str, nuevos) -> int:
        existentes = self._vlans.list(device=device_name)
        existentes_ids = {v.vlan_id for v in existentes}
        nuevos_ids = {v.vlan_id for v in nuevos}
        for vlan_id in existentes_ids - nuevos_ids:
            self._vlans.remove((vlan_id, device_name))
        for v in nuevos:
            v.device = device_name
            self._vlans.add(v)
        return len(existentes_ids - nuevos_ids)

    def _persistir_ports(self, device_name: str, nuevos) -> int:
        existentes = self._ports.list(device=device_name)
        existentes_ifs = {p.interface for p in existentes}
        nuevos_ifs = {p.interface for p in nuevos}
        for interface in existentes_ifs - nuevos_ifs:
            self._ports.remove((interface, device_name))
        for p in nuevos:
            p.device = device_name
            self._ports.add(p)
        return len(existentes_ifs - nuevos_ifs)

    def _persistir_svis(self, device_name: str, nuevas) -> int:
        existentes = self._interfaces.list(device=device_name)
        existentes_ids = {i.vlan_id for i in existentes}
        nuevas_ids = {i.vlan_id for i in nuevas}
        for vlan_id in existentes_ids - nuevas_ids:
            self._interfaces.remove((vlan_id, device_name))
        for i in nuevas:
            i.device = device_name
            self._interfaces.add(i)
        return len(existentes_ids - nuevas_ids)

    def sync_svis(self, device: "Device") -> None:
        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                nuevas = device.driver.get_svis(device, device.password)
        except Exception as exc:
            logger.exception("sync_svis failed device=%s", device.name)
            self._marcar_error(device.name, "svis_sync_error", str(exc))
            raise

        removed = self._persistir_svis(device.name, nuevas)

        self._marcar_ok(device.name, "svis_synced_at", "svis_sync_error")
        logger.info(
            "sync_svis OK device=%s persisted=%d removed=%d",
            device.name, len(nuevas), removed,
        )

    def sync_global_config(self, device: "Device") -> None:
        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                config = device.driver.get_global_config(device, device.password)
        except Exception as exc:
            logger.exception("sync_global_config failed device=%s", device.name)
            self._marcar_error(device.name, "global_config_sync_error", str(exc))
            raise

        config.device = device.name
        self._global_config.add(config)

        self._marcar_ok(device.name, "global_config_synced_at", "global_config_sync_error")
        logger.info("sync_global_config OK device=%s", device.name)

    def sync_arp_mac(self, device: "Device") -> None:
        from app.models.arp_mac import ArpMacTables

        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                arp_table = device.driver.get_arp_table(device, device.password)
                mac_table = device.driver.get_mac_table(device, device.password)
        except Exception as exc:
            logger.exception("sync_arp_mac failed device=%s", device.name)
            self._marcar_error(device.name, "arp_mac_sync_error", str(exc))
            raise

        self._arp_mac.add(ArpMacTables(device=device.name, arp_table=arp_table, mac_table=mac_table))

        self._marcar_ok(device.name, "arp_mac_synced_at", "arp_mac_sync_error")
        logger.info("sync_arp_mac OK device=%s", device.name)

    def sync_logs(self, device: "Device") -> None:
        from app.models.device_logs import DeviceLogs

        try:
            with self._coordinator.bloquear(device.name, timeout=_LOCK_TIMEOUT_S):
                log_output = device.driver.get_log_buffer(device, device.password)
        except Exception as exc:
            logger.exception("sync_logs failed device=%s", device.name)
            self._marcar_error(device.name, "logs_sync_error", str(exc))
            raise

        self._device_logs.add(DeviceLogs(device=device.name, log_output=log_output))

        self._marcar_ok(device.name, "logs_synced_at", "logs_sync_error")
        logger.info("sync_logs OK device=%s", device.name)

    def metadata(
        self, device_name: str, scope: str,
    ) -> tuple[Optional[datetime], Optional[str]]:
        cols = {
            "vlans": (DeviceModel.vlans_synced_at, DeviceModel.vlans_sync_error),
            "ports": (DeviceModel.ports_synced_at, DeviceModel.ports_sync_error),
            "svis": (
                DeviceModel.svis_synced_at,
                DeviceModel.svis_sync_error,
            ),
            "global_config": (
                DeviceModel.global_config_synced_at,
                DeviceModel.global_config_sync_error,
            ),
            "arp_mac": (
                DeviceModel.arp_mac_synced_at,
                DeviceModel.arp_mac_sync_error,
            ),
            "logs": (
                DeviceModel.logs_synced_at,
                DeviceModel.logs_sync_error,
            ),
        }
        if scope not in cols:
            raise ValueError(
                f"metadata(): scope inválido {scope!r} (esperado: vlans / ports / svis / global_config / arp_mac / logs)"
            )
        col_ts, col_err = cols[scope]
        with get_session() as session:
            row = (
                session.query(col_ts, col_err)
                .filter(DeviceModel.name == device_name)
                .first()
            )
            return (row[0], row[1]) if row else (None, None)

    def _marcar_ok(self, device_name: str, ts_field: str, err_field: str) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            session.execute(
                update(DeviceModel)
                .where(DeviceModel.name == device_name)
                .values(**{ts_field: now, err_field: None})
            )

    def _marcar_error(self, device_name: str, err_field: str, mensaje: str) -> None:
        mensaje = mensaje[:_MAX_ERROR_LEN]
        with get_session() as session:
            session.execute(
                update(DeviceModel)
                .where(DeviceModel.name == device_name)
                .values(**{err_field: mensaje})
            )
