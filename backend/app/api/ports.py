from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.exceptions import ValidationError
from app.core.response import ok
from app.core.scope import authorize_device, obtener_scope, require_authenticated, require_device
from app.models.port import Puerto
from app.models.visibility_scope import VisibilityScope
from app.schemas.device_sync import SyncedResource
from app.schemas.port import (
    PortAccessVlanUpdateRequest,
    PortAdminStateUpdateRequest,
    PortBatchChangeItem,
    PortBatchRequest,
    PortDescriptionClearRequest,
    PortDescriptionUpdateRequest,
    PortEnableRequest,
    PortPoeUpdateRequest,
    PortRead,
    PortResetRequest,
    PortSetAccessModeRequest,
    PortSetTrunkModeRequest,
    PortShutdownRequest,
    PortStormControlUpdateRequest,
    PortTrunkVlansUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _nombre_completo(vendor: str, interface: str) -> str:
    from app.services.parsers.port_parser import expandir_nombre_interfaz, expandir_nombre_interfaz_ios

    if vendor == "huawei_vrp":
        return expandir_nombre_interfaz(interface)
    if vendor == "cisco_ios":
        return expandir_nombre_interfaz_ios(interface)
    return interface

def _authz_device(
    scope: VisibilityScope, device_name: str, *, min_role: str, device: "Device | None" = None,
) -> None:
    resolved = (device.site_id, device.device_group_id) if device is not None else None
    authorize_device(scope, device_name, "port_device_op", min_role, resolved=resolved)


def _require_port_driver_with(device: "Device", method_name: str):
    from app.services.vendors.base import VendorDriver

    driver = device.driver
    if getattr(type(driver), method_name) is getattr(VendorDriver, method_name):
        logger.info(
            "Port %s unimplemented on driver=%s for device=%s",
            method_name, type(driver).__name__, device.name,
        )
        raise HTTPException(
            status_code=501,
            detail={
                "error_code": "VENDOR_NOT_SUPPORTED",
                "message": "This port operation is not yet supported for this vendor.",
            },
        )
    return driver


def _reject_if_aggregate_write(vendor: str, interface: str, *fields: str) -> None:
    from app.services.parsers.port_parser import is_aggregate_interface

    if is_aggregate_interface(vendor, interface):
        raise ValidationError(
            f"{'/'.join(fields)} cannot be configured on aggregate interface "
            f"'{interface}' (Eth-Trunk/Port-channel) -- no physical link to "
            "power, and storm-control support on an aggregate is vendor/"
            "platform-dependent and unsupported here."
        )


@router.get(
    "/",
    summary="List ports",
    description=(
        "Retrieve the normalized port inventory of a single device. "
        "Returns interface name, description, admin and operational "
        "state, switchport mode, access / trunk VLAN information, and "
        "(when exposed by the device) PoE / speed / duplex.  Read-only — "
        "no configuration changes.  Requires observer role or higher; "
        "site-scoped users may only query devices in their allowed sites."
    ),
)
def list_ports(
    name: str,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import (
        device_sync_service, puerto_repository, redis_coordinator, svi_repository,
    )
    from app.models.management_vlan import detectar_vlan_gestion

    _authz_device(scope, name, min_role="observer")
    dev = require_device(name)
    puertos = puerto_repository.list(device=name)
    payload = {
        "device": dev.name,
        "vendor": dev.vendor,
        "count": len(puertos),
        "management_vlan": detectar_vlan_gestion(dev.host, svi_repository.list(device=name)),
        "ports": [
            PortRead(
                name=p.interface, name_full=_nombre_completo(dev.vendor, p.interface),
                description=p.description, admin_up=p.admin_up,
                operational_up=p.operational_up, mode=p.mode or "unknown", access_vlan=p.access_vlan,
                allowed_vlans=p.allowed_vlans,
                storm_control_enabled=p.storm_control_enabled,
                storm_control_threshold=p.storm_control_threshold,
                kind=p.kind,
            ).model_dump()
            for p in puertos
        ],
    }
    synced_at, sync_error = device_sync_service.metadata(name, "ports")
    envelope = SyncedResource(
        data=payload,
        synced_at=synced_at,
        sync_error=sync_error,
        sync_in_progress=redis_coordinator.esta_ocupado(name),
    ).model_dump(mode="json")
    return ok(envelope)


@router.patch(
    "/description",
    status_code=202,
    summary="Set port description",
    description=(
        "Assign a description to a single interface on a device.  To "
        "clear it, use `DELETE .../description` instead — a value is "
        "always required here.  Executed asynchronously: the response "
        "carries a `group_job_id` and per-device job entry the frontend "
        "can poll via `GET /api/v1/jobs/{job_id}` and "
        "`GET /api/v1/group-jobs/{id}`.  Pre-state is captured for "
        "rollback — if the device-side change fails, the original "
        "description is restored automatically.  Requires operator role "
        "or higher; site-scoped users may only target devices in their "
        "allowed sites."
    ),
)
def update_port_description(
    name: str,
    data: PortDescriptionUpdateRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, description=data.description)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "update_port_description")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.delete(
    "/description",
    status_code=202,
    summary="Clear port description",
    description=(
        "Clear the description of a single interface on a device "
        "(`undo description` on Huawei VRP, `no description` on Cisco "
        "IOS).  Executed asynchronously: the response carries a "
        "`group_job_id` and per-device job entry the frontend can poll "
        "via `GET /api/v1/jobs/{job_id}` and `GET /api/v1/group-jobs/{id}`.  "
        "Pre-state is captured for rollback — if the device-side change "
        "fails, the original description is restored automatically.  "
        "Requires operator role or higher; site-scoped users may only "
        "target devices in their allowed sites."
    ),
)
def clear_port_description(
    name: str,
    data: PortDescriptionClearRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    entidad = Puerto(interface=data.interface, description="")
    entidad.validar()

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "update_port_description")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.patch(
    "/admin-state",
    status_code=202,
    summary="Set port admin state",
    description=(
        "Administratively enable or disable a single interface.  "
        "``enabled=true`` runs ``undo shutdown`` (Huawei) / ``no shutdown`` "
        "(Cisco); ``enabled=false`` runs ``shutdown``.  Executed "
        "asynchronously: the response carries a ``group_job_id`` and per-"
        "device job entry the frontend can poll via "
        "``GET /api/v1/jobs/{job_id}`` and ``GET /api/v1/group-jobs/{id}``.  "
        "Pre-state is captured for rollback — if the device-side change "
        "fails, the original admin state is restored automatically.  "
        "Requires operator role or higher; site-scoped users may only "
        "target devices in their allowed sites."
    ),
)
def set_port_admin_state(
    name: str,
    data: PortAdminStateUpdateRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, admin_up=data.enabled)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_port_admin_state")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.patch(
    "/access-vlan",
    status_code=202,
    summary="Set port access VLAN",
    description=(
        "Assign an access VLAN to a single interface — or the native VLAN "
        "(PVID) if the port is currently in trunk mode.  The orchestration "
        "layer reads the port's live mode and dispatches accordingly; "
        "other modes are rejected.  Executed asynchronously: the response "
        "carries a ``group_job_id`` and per-device job entry the frontend "
        "can poll via ``GET /api/v1/jobs/{job_id}`` and "
        "``GET /api/v1/group-jobs/{id}``.  Pre-state is captured for "
        "rollback — if the device-side change fails, the original VLAN is "
        "restored automatically.  Requires operator role or higher; "
        "site-scoped users may only target devices in their allowed sites."
    ),
)
def set_port_access_vlan(
    name: str,
    data: PortAccessVlanUpdateRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, access_vlan=data.vlan_id)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_port_access_vlan")
    _require_port_driver_with(dev, "set_trunk_pvid_vlan")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.patch(
    "/trunk-vlans",
    status_code=202,
    summary="Set trunk allowed VLANs",
    description=(
        "Modify the trunk allowed-VLAN list on a single interface.  "
        "``mode='replace'`` sets the list to exactly ``vlans``; "
        "``mode='add'`` unions ``vlans`` with the current list; "
        "``mode='remove'`` subtracts ``vlans`` from the current list.  "
        "The port must already be in trunk mode; a ``remove`` that would "
        "leave the trunk with no allowed VLANs is rejected.  Executed "
        "asynchronously: the response carries a ``group_job_id`` and per-"
        "device job entry the frontend can poll via "
        "``GET /api/v1/jobs/{job_id}`` and ``GET /api/v1/group-jobs/{id}``.  "
        "Only the difference is sent to the device (VLANs to add, then VLANs "
        "to remove); VLANs that don't change are never rewritten.  "
        "Pre-state is captured for rollback — if the device-side change "
        "fails, only what this request changed is undone (the VLANs it "
        "added are removed, the ones it removed are re-added).  "
        "Requires operator role or higher; site-scoped users may only "
        "target devices in their allowed sites."
    ),
)
def set_trunk_allowed_vlans(
    name: str,
    data: PortTrunkVlansUpdateRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(
            interface=data.interface,
            allowed_vlans=list(data.vlans),
            allowed_vlan_operation=data.mode,
        )
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_trunk_allowed_vlans")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.post(
    "/access-mode",
    status_code=202,
    summary="Set port to access mode",
    description=(
        "Set a single interface to access mode with the given access VLAN, "
        "atomically (mode + VLAN applied together).  "
        "Replaces the old generic ``/configure`` endpoint for this specific, "
        "well-defined operation — there is no meaningful 'just change mode, "
        "keep whatever VLAN was there' case.  "
        "Pre-state is captured for rollback — if the device-side change "
        "fails, the port's original mode/VLAN are restored automatically.  "
        "Executed asynchronously: the response carries a ``group_job_id`` and "
        "per-device job entry the frontend can poll via ``GET /api/v1/jobs/{job_id}`` "
        "and ``GET /api/v1/group-jobs/{id}``.  "
        "Requires operator role or higher; site-scoped users may only target "
        "devices in their allowed sites."
    ),
)
def set_port_access_mode(
    name: str,
    data: PortSetAccessModeRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, mode="access", access_vlan=data.access_vlan)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_access_mode")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.post(
    "/trunk-mode",
    status_code=202,
    summary="Set port to trunk mode",
    description=(
        "Set a single interface to trunk mode with the given native VLAN "
        "(PVID) and allowed-VLAN list.  Both are the desired final state "
        "(replace semantics), not an add/remove.  If the port is ALREADY a "
        "trunk with a readable VLAN list, only the difference is sent (the "
        "native VLAN if it changes, VLANs to add, then VLANs to remove) — "
        "no ``link-type``/``switchport mode`` change and no full rewrite of "
        "the list; nothing is sent if it already matches.  Otherwise (coming "
        "from access, hybrid, or an unreadable state) the full atomic mode "
        "change is applied.  On Cisco the delta path leaves the "
        "administrative mode untouched, so a DTP-negotiated trunk stays "
        "negotiated.  Use ``PATCH /ports/access-vlan``/``PATCH "
        "/ports/trunk-vlans`` to adjust either dimension individually.  "
        "Pre-state is captured for rollback — if the device-side change "
        "fails, only what this request changed is undone (VLANs it "
        "added/removed and the native VLAN, if it is still the one it set); "
        "coming from access/unreadable, the original mode/VLANs are restored.  "
        "Executed asynchronously: the response carries a ``group_job_id`` and "
        "per-device job entry the frontend can poll via ``GET /api/v1/jobs/{job_id}`` "
        "and ``GET /api/v1/group-jobs/{id}``.  "
        "Requires operator role or higher; site-scoped users may only target "
        "devices in their allowed sites."
    ),
)
def set_port_trunk_mode(
    name: str,
    data: PortSetTrunkModeRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(
            interface=data.interface, mode="trunk",
            access_vlan=data.native_vlan, allowed_vlans=list(data.allowed_vlans),
        )
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_trunk_mode")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.post(
    "/shutdown",
    status_code=202,
    summary="Shutdown port",
    description=(
        "Administratively disable a single interface (``shutdown`` command).  "
        "No-op when the port is already administratively down.  "
        "Pre-state is captured for rollback — if the device-side command fails "
        "and the port was previously up, the original admin state is restored "
        "automatically.  "
        "Executed asynchronously: the response carries a ``group_job_id`` and "
        "per-device job entry.  "
        "Requires operator role or higher; site-scoped users may only target "
        "devices in their allowed sites."
    ),
)
def shutdown_port(
    name: str,
    data: PortShutdownRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, admin_up=False)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_port_admin_state")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.post(
    "/enable",
    status_code=202,
    summary="Enable port",
    description=(
        "Administratively enable a single interface (``no shutdown`` / "
        "``undo shutdown`` command).  "
        "No-op when the port is already administratively up.  "
        "Pre-state is captured for rollback — if the device-side command fails "
        "and the port was previously down, the original admin state is restored "
        "automatically.  "
        "Executed asynchronously: the response carries a ``group_job_id`` and "
        "per-device job entry.  "
        "Requires operator role or higher; site-scoped users may only target "
        "devices in their allowed sites."
    ),
)
def enable_port(
    name: str,
    data: PortEnableRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, admin_up=True)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_port_admin_state")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.patch(
    "/poe",
    status_code=202,
    summary="Set port PoE state",
    description=(
        "Enable or disable Power-over-Ethernet on a single interface "
        "(RF-PUERTO-09).  ``enabled=true`` runs ``power inline auto`` "
        "(Cisco) / ``poe enable`` (Huawei); ``enabled=false`` runs "
        "``power inline never`` / ``poe disable``.  Executed asynchronously: "
        "the response carries a ``group_job_id`` and per-device job entry "
        "the frontend can poll via ``GET /api/v1/jobs/{job_id}`` and "
        "``GET /api/v1/group-jobs/{id}``.  Requires operator role or "
        "higher; site-scoped users may only target devices in their "
        "allowed sites."
    ),
)
def set_port_poe(
    name: str,
    data: PortPoeUpdateRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(interface=data.interface, poe_enabled=data.enabled)
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_port_poe")
    _reject_if_aggregate_write(dev.vendor, data.interface, "PoE")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.patch(
    "/storm-control",
    status_code=202,
    summary="Set port storm-control state",
    description=(
        "Enable or disable broadcast storm-control on a single interface, "
        "with a single percentage threshold (RF-PUERTO-07, simplified "
        "scope — one enable flag + one global threshold, not the 3 traffic "
        "types real hardware exposes separately).  ``threshold_percent`` is "
        "required when ``enabled=true``.  Executed asynchronously: the "
        "response carries a ``group_job_id`` and per-device job entry.  "
        "Requires operator role or higher; site-scoped users may only "
        "target devices in their allowed sites."
    ),
)
def set_port_storm_control(
    name: str,
    data: PortStormControlUpdateRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = Puerto(
            interface=data.interface,
            storm_control_enabled=data.enabled,
            storm_control_threshold=data.threshold_percent,
            storm_control_action=data.action,
            storm_control_trap=data.trap,
        )
        entidad.validar()
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "set_storm_control")
    _reject_if_aggregate_write(dev.vendor, data.interface, "Storm-control")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.post(
    "/reset",
    status_code=202,
    summary="Reset port to defaults",
    description=(
        "Reset a single interface to its factory-default configuration "
        "(RF-PUERTO-10 — ``default interface`` on Cisco, ``clear "
        "configuration interface`` on Huawei).  Clears VLAN assignment, "
        "description, PoE, storm-control and admin state back to device "
        "defaults.  Executed asynchronously: the response carries a "
        "``group_job_id`` and per-device job entry.  Requires operator "
        "role or higher; site-scoped users may only target devices in "
        "their allowed sites."
    ),
)
def reset_port(
    name: str,
    data: PortResetRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    entidad = Puerto(interface=data.interface, reset=True)
    entidad.validar()

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)
    _require_port_driver_with(dev, "reset_port")

    group_job_id, jobs = group_operation_runner.encolar(entidad, [name], current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


def expandir_a_puertos(cambio: PortBatchChangeItem) -> list[Puerto]:
    puertos: list[Puerto] = []
    if cambio.mode is not None:
        puertos.append(Puerto(
            interface=cambio.interface, mode=cambio.mode, access_vlan=cambio.access_vlan,
            allowed_vlans=list(cambio.allowed_vlans) if cambio.allowed_vlans else None,
        ))
    else:
        if cambio.access_vlan is not None:
            puertos.append(Puerto(interface=cambio.interface, access_vlan=cambio.access_vlan))
        if cambio.allowed_vlans is not None:
            puertos.append(Puerto(
                interface=cambio.interface, allowed_vlans=list(cambio.allowed_vlans),
                allowed_vlan_operation=cambio.allowed_vlan_operation,
            ))
    if cambio.storm_control_enabled is not None:
        puertos.append(Puerto(
            interface=cambio.interface, storm_control_enabled=cambio.storm_control_enabled,
            storm_control_threshold=cambio.storm_control_threshold,
            storm_control_action=cambio.storm_control_action,
            storm_control_trap=cambio.storm_control_trap,
        ))
    if cambio.description is not None:
        puertos.append(Puerto(interface=cambio.interface, description=cambio.description))
    if cambio.admin_up is not None:
        puertos.append(Puerto(interface=cambio.interface, admin_up=cambio.admin_up))
    if cambio.poe_enabled is not None:
        puertos.append(Puerto(interface=cambio.interface, poe_enabled=cambio.poe_enabled))
    if not puertos:
        raise ValueError(f"no changes provided for interface {cambio.interface!r}")
    return puertos


@router.post(
    "/batch",
    status_code=202,
    summary="Batch-update multiple ports (or multiple fields on one port) in 1 connection",
    description=(
        "Apply N changes -- across multiple interfaces, multiple fields on "
        "one interface, or any mix -- in a **single** SSH connection to the "
        "device instead of one connection per change. Each entry in "
        "`changes` may carry the full config of one port (multiple fields "
        "together) or just one field. Field-level no-op detection still "
        "applies per entry (unchanged values aren't re-sent). If the batch "
        "fails partway, the whole job fails and rollback attempts to "
        "restore every entry that did change -- there is no partial-success "
        "reporting per entry. Executed asynchronously: the response "
        "carries a `group_job_id` and a single job entry (1 job = 1 "
        "connection, not 1 per change). Requires operator role or higher; "
        "site-scoped users may only target devices in their allowed sites."
    ),
)
def batch_update_ports(
    name: str,
    data: PortBatchRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    recursos: list[Puerto] = []
    try:
        for cambio in data.changes:
            nuevos = expandir_a_puertos(cambio)
            for puerto in nuevos:
                puerto.validar()
            recursos.extend(nuevos)
        por_interfaz: dict[str, list[Puerto]] = {}
        for p in recursos:
            if p.mode is not None or p.access_vlan is not None or p.allowed_vlans is not None:
                por_interfaz.setdefault(p.interface, []).append(p)
        conflictivas = sorted(
            i for i, ps in por_interfaz.items()
            if sum(1 for p in ps if p.allowed_vlans is not None) > 1
            or (len(ps) > 1 and any(p.mode is not None for p in ps))
        )
        if conflictivas:
            raise ValueError(
                "more than one change targets the mode/VLANs of "
                f"{', '.join(conflictivas)} -- combine them into a single entry per interface"
            )
    except ValueError as exc:
        raise ValidationError(str(exc))

    dev = require_device(name)
    _authz_device(scope, name, min_role="operator", device=dev)

    for p in recursos:
        fields = [f for f, v in (("PoE", p.poe_enabled), ("Storm-control", p.storm_control_enabled)) if v is not None]
        if fields:
            _reject_if_aggregate_write(dev.vendor, p.interface, *fields)

    group_job_id, job_entry = group_operation_runner.encolar_lote(recursos, name, current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": [job_entry]})
