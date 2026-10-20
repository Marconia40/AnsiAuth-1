from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.exceptions import NotFoundError, ValidationError
from app.core.response import ok
from app.core.scope import obtener_scope, require_authenticated
from app.models.visibility_scope import VisibilityScope

router = APIRouter()


@router.get(
    "/summary",
    summary="Dashboard aggregation for a scope",
    description=(
        "Return aggregated counters (devices/vlans/ports/svis/jobs) used "
        "by the dashboard cards. Replaces the N+1 pattern where the "
        "frontend fetched the device list plus one vlans/ports/svis query "
        "per device.\n\n"
        "Scopes soportados via ?scope=:\n"
        "* `org`   — todos los devices visibles al caller\n"
        "* `site`  — devices del site (requiere ?id=<site_id>)\n"
        "* `group` — devices del device_group (requiere ?id=<group_id>)\n"
        "* `device`— un solo device (requiere ?name=<device_name>)\n\n"
        "Autorización: cualquier user autenticado. Si el user no tiene "
        "visibilidad sobre nada del scope pedido, la respuesta vuelve "
        "con contadores en cero (no 403). Si el site/group/device de la "
        "URL no existe: 404.\n\n"
        "`?include_global_config=true` agrega una sección adicional con "
        "SNMP/NTP/DNS/logging/ACLs por device (opt-in, no forma parte del "
        "dashboard normal)."
    ),
)
def get_dashboard_summary(
    scope: str = Query(
        ...,
        pattern="^(org|site|group|device)$",
        description="Tipo de agregación",
    ),
    id: Optional[int] = Query(
        default=None,
        ge=1,
        description="Site o group ID. Requerido para scope=site y scope=group.",
    ),
    name: Optional[str] = Query(
        default=None,
        description="Device name. Requerido para scope=device.",
    ),
    jobs_days: int = Query(
        default=7,
        ge=1,
        le=30,
        description="Ventana temporal de jobs a agregar (1–30 días).",
    ),
    include_global_config: bool = Query(
        default=False,
        description=(
            "Opt-in: agrega la sección `global_config` (SNMP/NTP/DNS/"
            "logging/ACLs por device). Default false — el dashboard normal "
            "no paga este costo; solo lo pide la vista de Global Config "
            "cruzada."
        ),
    ),
    current_user: dict = Depends(require_authenticated),
    visibility_scope: VisibilityScope = Depends(obtener_scope),
):
    from app.composition import dashboard_service

    if scope in ("site", "group") and id is None:
        raise ValidationError(f"scope={scope} requires 'id' query param")
    if scope == "device" and not name:
        raise ValidationError("scope=device requires 'name' query param")
    if scope == "org" and (id is not None or name is not None):
        raise ValidationError(
            "scope=org does not accept 'id' or 'name' params",
        )

    payload = dashboard_service.resumir(
        scope_kind=scope,
        scope_id=id,
        device_name=name,
        jobs_days=jobs_days,
        visibility_scope=visibility_scope,
        include_global_config=include_global_config,
    )

    if payload is None:
        target = f"{scope}={id or name}"
        raise NotFoundError(f"Scope target '{target}' not found")

    return ok(payload)


@router.post(
    "/refresh",
    status_code=202,
    summary="Reactive refresh: sync only stale devices in a scope",
    description=(
        "Encola una sync de VLANs + ports + SVIs (scope ``all``) para "
        "los devices del scope cuyo último sync es más viejo que "
        "``stale_threshold_s`` (default ``SYNC_STALE_THRESHOLD_S``, 15 min). Devices frescos "
        "se omiten silenciosamente. Si un device ya tiene una sync "
        "pending (coalescing), tampoco se re-encola.\n\n"
        "El frontend llama este endpoint al abrir el dashboard (refresh "
        "reactivo). La carga sostenida del inventory la resuelve "
        "``sync_stale_devices_task`` (Celery Beat, cada ~20 min); este "
        "endpoint es sólo el disparador on-open que evita mostrar data "
        "vieja cuando el usuario vuelve al dashboard tras un rato.\n\n"
        "Params iguales a ``/dashboard/summary`` (scope + id/name). "
        "Devuelve 202 con lista de task_ids encolados. El frontend "
        "sigue polling ``GET /dashboard/summary`` — cuando "
        "``devices.sync_in_progress_count`` vuelve a 0 los syncs "
        "terminaron.\n\n"
        "`?include_global_config=true` además encola, con el mismo "
        "criterio de staleness/coalescing, un sync scope=``global_config`` "
        "(SNMP/NTP/DNS/logging/ACLs) independiente del combo ``all`` de "
        "arriba. Opt-in a propósito — ``global_config`` está excluido del "
        "refresh automático porque trae running-configs completos; solo "
        "la vista de Global Config cruzada debe pedirlo explícitamente."
    ),
)
def refresh_dashboard_scope(
    scope: str = Query(..., pattern="^(org|site|group|device)$"),
    id: Optional[int] = Query(default=None, ge=1),
    name: Optional[str] = Query(default=None),
    stale_threshold_s: Optional[int] = Query(
        default=None,
        ge=0,
        le=86400,
        description="Un device se considera 'stale' si su último sync es "
                    "más viejo que este umbral en segundos (0 fuerza refresh). "
                    "Sin valor, se usa SYNC_STALE_THRESHOLD_S (15 min por defecto).",
    ),
    include_global_config: bool = Query(
        default=False,
        description=(
            "Opt-in: además encola sync scope=global_config para los "
            "devices cuyo global_config_synced_at está stale. Default "
            "false — nunca se activa como parte del refresh automático."
        ),
    ),
    current_user: dict = Depends(require_authenticated),
    visibility_scope: VisibilityScope = Depends(obtener_scope),
):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, or_

    from app.composition import dashboard_service, redis_coordinator
    from app.db.models import DeviceModel
    from app.db.session import get_session
    from app.tasks import _encolar_sync_si_no_pendiente

    if scope in ("site", "group") and id is None:
        raise ValidationError(f"scope={scope} requires 'id' query param")
    if scope == "device" and not name:
        raise ValidationError("scope=device requires 'name' query param")
    if scope == "org" and (id is not None or name is not None):
        raise ValidationError(
            "scope=org does not accept 'id' or 'name' params",
        )

    resuelto = dashboard_service.resolver_devices_del_scope(
        scope, id, name, visibility_scope,
    )
    if resuelto is None:
        target = f"{scope}={id or name}"
        raise NotFoundError(f"Scope target '{target}' not found")

    device_names, _ = resuelto
    if not device_names:
        return ok({"devices_queued": 0, "tasks_dispatched": 0, "tasks": []})

    if stale_threshold_s is None:
        from app.tasks import SYNC_STALE_THRESHOLD_S
        stale_threshold_s = SYNC_STALE_THRESHOLD_S
    threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_s)
    with get_session() as session:
        stale_rows = (
            session.query(DeviceModel.name)
            .filter(DeviceModel.name.in_(device_names))
            .filter(
                or_(
                    DeviceModel.vlans_synced_at.is_(None),
                    DeviceModel.ports_synced_at.is_(None),
                    DeviceModel.svis_synced_at.is_(None),
                    DeviceModel.vlans_synced_at < threshold,
                    DeviceModel.ports_synced_at < threshold,
                    DeviceModel.svis_synced_at < threshold,
                )
            )
            .order_by(DeviceModel.name.asc())
            .all()
        )
    stale_names = [n for (n,) in stale_rows]

    encolados = 0
    for device_name in stale_names:
        if _encolar_sync_si_no_pendiente(device_name, "all"):
            encolados += 1

    gc_encolados = 0
    gc_stale_count = 0
    if include_global_config:
        with get_session() as session:
            gc_stale_rows = (
                session.query(DeviceModel.name)
                .filter(DeviceModel.name.in_(device_names))
                .filter(
                    or_(
                        DeviceModel.global_config_synced_at.is_(None),
                        DeviceModel.global_config_synced_at < threshold,
                    )
                )
                .order_by(DeviceModel.name.asc())
                .all()
            )
        gc_stale_names = [n for (n,) in gc_stale_rows]
        gc_stale_count = len(gc_stale_names)
        for device_name in gc_stale_names:
            if _encolar_sync_si_no_pendiente(device_name, "global_config"):
                gc_encolados += 1

    result = {
        "devices_queued": encolados,
        "devices_skipped_fresh": len(device_names) - len(stale_names),
        "devices_skipped_coalesced": len(stale_names) - encolados,
        "tasks_dispatched": encolados,
    }
    if include_global_config:
        result["global_config_devices_queued"] = gc_encolados
        result["global_config_devices_skipped_fresh"] = len(device_names) - gc_stale_count
        result["global_config_devices_skipped_coalesced"] = gc_stale_count - gc_encolados
    return ok(result)
