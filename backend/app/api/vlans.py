import logging

from fastapi import APIRouter, Depends, Query

from app.core.exceptions import ValidationError
from app.core.response import ok
from app.core.scope import authorize_device, obtener_scope, require_authenticated, require_device
from app.models.visibility_scope import VisibilityScope
from app.models.vlan import VLAN
from app.schemas.device_sync import SyncedResource
from app.schemas.vlan import VLANBatchRequest, VLANCreate, VLANDelete, VLANUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


def _authz_devices(scope: VisibilityScope, device_names, *, min_role: str, resolved_by_name=None) -> None:
    for name in device_names:
        dev = resolved_by_name.get(name) if resolved_by_name else None
        resolved = (dev.site_id, dev.device_group_id) if dev is not None else None
        authorize_device(scope, name, "vlan_device_op", min_role, resolved=resolved)


def _leer_vlans_cache(device_name: str) -> dict:
    from app.composition import device_sync_service, redis_coordinator, vlan_repository

    require_device(device_name)
    vlans = vlan_repository.list(device=device_name)
    synced_at, sync_error = device_sync_service.metadata(device_name, "vlans")
    return SyncedResource(
        data=[v.to_dict() for v in vlans],
        synced_at=synced_at,
        sync_error=sync_error,
        sync_in_progress=redis_coordinator.esta_ocupado(device_name),
    ).model_dump(mode="json")


@router.get(
    "/",
    summary="List VLANs",
    description=(
        "Retrieve the VLAN table from one or more devices. "
        "Pass `device=switch-01` for a single device or `devices=switch-01&devices=switch-02` "
        "for multiple. Requires observer role or higher."
    ),
)
def get_vlans(
    device: str | None = None,
    devices: list[str] | None = Query(default=None),
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    if devices:
        _authz_devices(scope, devices, min_role="observer")
        result = {dev: _leer_vlans_cache(dev) for dev in devices}
        return ok(result)

    if device is None:
        from app.core.config import EXECUTION_MODE
        if EXECUTION_MODE != "mock":
            raise ValidationError("'device' query parameter is required")
        from app.services.vendors.mock import _mock_vlans
        envelope = SyncedResource(
            data=[v.to_dict() for v in _mock_vlans],
            synced_at=None, sync_error=None, sync_in_progress=False,
        ).model_dump(mode="json")
        return ok(envelope)

    _authz_devices(scope, [device], min_role="observer")
    return ok(_leer_vlans_cache(device))


@router.post(
    "/",
    status_code=202,
    summary="Create VLAN",
    description=(
        "Create a new VLAN on one or more devices via Ansible. "
        "Each device gets its own background job — the response contains a job ID per device. "
        "Poll `GET /api/v1/jobs/{job_id}` for execution status. "
        "Requires operator role or higher on every target device."
    ),
)
def create_vlan(
    vlan: VLANCreate,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = VLAN(vlan_id=vlan.vlan_id, name=vlan.name)
        entidad.validar()
    except ValueError as e:
        raise ValidationError(str(e))
    devices_by_name = {name: require_device(name) for name in vlan.devices}
    _authz_devices(scope, vlan.devices, min_role="operator", resolved_by_name=devices_by_name)
    group_job_id, jobs = group_operation_runner.encolar(entidad, vlan.devices, current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.delete(
    "/{vlan_id}",
    status_code=202,
    summary="Delete VLAN",
    description=(
        "Remove a VLAN from one or more devices via Ansible. "
        "Returns a job ID per device. Reserved VLANs (1, 1002–1005) cannot be deleted. "
        "Requires admin role on every target device."
    ),
)
def delete_vlan(
    vlan_id: int,
    data: VLANDelete,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = VLAN(vlan_id=vlan_id, eliminar=True)
    except ValueError as e:
        raise ValidationError(str(e))
    devices_by_name = {name: require_device(name) for name in data.devices}
    _authz_devices(scope, data.devices, min_role="admin", resolved_by_name=devices_by_name)
    group_job_id, jobs = group_operation_runner.encolar(entidad, data.devices, current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})


@router.post(
    "/batch",
    status_code=202,
    summary="Batch VLAN operations on multiple devices in 1 SSH session per device",
    description=(
        "Apply N VLAN operations (create / rename / delete, in any mix) to M "
        "devices. Each device gets **one** background job that runs every "
        "operation in a **single** SSH session -- instead of N jobs with N "
        "sessions. Response carries a `group_job_id` and one job entry per "
        "device. Per-entry no-op detection still applies (e.g. a create for "
        "a VLAN that already has the same name is skipped). If the batch "
        "fails partway, rollback attempts to restore every entry that did "
        "change. A batch containing at least one deletion requires admin "
        "role on every target device; create/rename-only batches accept "
        "operator role."
    ),
)
def batch_vlans(
    data: VLANBatchRequest,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    recursos: list[VLAN] = []
    try:
        for change in data.changes:
            if change.eliminar:
                entidad = VLAN(vlan_id=change.vlan_id, eliminar=True)
            else:
                entidad = VLAN(vlan_id=change.vlan_id, name=change.name or "")
                entidad.validar()
            recursos.append(entidad)
    except ValueError as e:
        raise ValidationError(str(e))

    devices_by_name = {name: require_device(name) for name in data.devices}
    any_delete = any(r.eliminar for r in recursos)
    min_role = "admin" if any_delete else "operator"
    _authz_devices(scope, data.devices, min_role=min_role, resolved_by_name=devices_by_name)

    import uuid
    group_job_id = str(uuid.uuid4())
    job_entries: list[dict] = []
    for device_name in data.devices:
        _, entry = group_operation_runner.encolar_lote(
            recursos, device_name, current_user["username"], group_job_id=group_job_id,
        )
        job_entries.append(entry)
    return ok({"group_job_id": group_job_id, "jobs": job_entries})


@router.patch(
    "/{vlan_id}",
    status_code=202,
    summary="Update VLAN",
    description=(
        "Update the description of an existing VLAN on one or more devices. "
        "Returns a job ID per device. Requires operator role or higher on every target device."
    ),
)
def update_vlan(
    vlan_id: int,
    data: VLANUpdate,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import group_operation_runner

    try:
        entidad = VLAN(vlan_id=vlan_id, name=data.description)
        entidad.validar()
    except ValueError as e:
        raise ValidationError(str(e))
    devices_by_name = {name: require_device(name) for name in data.devices}
    _authz_devices(scope, data.devices, min_role="operator", resolved_by_name=devices_by_name)
    group_job_id, jobs = group_operation_runner.encolar(entidad, data.devices, current_user["username"])
    return ok({"group_job_id": group_job_id, "jobs": jobs})
