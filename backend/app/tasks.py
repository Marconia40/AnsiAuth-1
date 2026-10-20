import logging
import os
import uuid

from app.worker import celery_app

logger = logging.getLogger(__name__)

SYNC_STALE_INTERVAL_MIN: int = int(os.getenv("SYNC_STALE_INTERVAL_MIN", "20"))

SYNC_STALE_THRESHOLD_S: int = int(os.getenv("SYNC_STALE_THRESHOLD_S", "900"))

SYNC_STALE_STAGGER_S: int = int(os.getenv("SYNC_STALE_STAGGER_S", "3"))


@celery_app.task(name="ansiauth.orquestador.ejecutar")
def ejecutar_task(recurso_dict: dict, tipo_recurso: str, device_name: str, actor: str, job_id: str) -> None:
    from app.composition import job_repository, orquestador
    from app.models.svi import SVI
    from app.models.port import Puerto
    from app.models.vlan import VLAN
    from app.models.global_config import GlobalConfig
    from app.models.save_config import GuardarConfig

    _TIPOS = {
        "vlan": VLAN, "puerto": Puerto, "svi": SVI, "global_config": GlobalConfig,
        "save_config": GuardarConfig,
    }
    recurso = _TIPOS[tipo_recurso](**recurso_dict)
    job = job_repository.get(job_id)
    orquestador.ejecutar(recurso, device_name, actor, job)


@celery_app.task(name="ansiauth.orquestador.ejecutar_lote")
def ejecutar_lote_task(
    recursos_dict: list[dict], tipo_recurso: str, device_name: str, actor: str, job_id: str,
) -> None:
    from app.composition import job_repository, orquestador
    from app.models.svi import SVI
    from app.models.port import Puerto
    from app.models.vlan import VLAN

    _TIPOS = {"puerto": Puerto, "svi": SVI, "vlan": VLAN}
    cls = _TIPOS[tipo_recurso]
    recursos = [cls(**d) for d in recursos_dict]
    job = job_repository.get(job_id)
    orquestador.ejecutar_lote(recursos, device_name, actor, job)


@celery_app.task(name="ansiauth.orquestador.retry_rollback")
def retry_rollback_task(original_job_id: str, new_job_id: str, actor: str) -> None:
    from app.composition import job_repository, orquestador

    original = job_repository.get(original_job_id)
    new_job = job_repository.get(new_job_id)
    if original is None or new_job is None:
        logger.warning(
            "retry_rollback_task: original=%s o new_job=%s no existe -- "
            "saltando (probablemente eliminado post-encolar).",
            original_job_id, new_job_id,
        )
        return
    orquestador.retry_rollback(original, new_job, actor)


@celery_app.task(name="ansiauth.device.sync")
def sync_device_task(device_name: str, scope: str) -> None:
    from app.composition import device_repository, device_sync_service, redis_coordinator

    redis_coordinator.limpiar_sync_pendiente(device_name, scope)

    device = device_repository.get(device_name)
    if device is None:
        logger.warning("sync_device_task: device '%s' no existe, saltando", device_name)
        return

    if scope == "vlans":
        device_sync_service.sync_vlans(device)
    elif scope == "ports":
        device_sync_service.sync_ports(device)
    elif scope == "svis":
        device_sync_service.sync_svis(device)
    elif scope == "global_config":
        device_sync_service.sync_global_config(device)
    elif scope == "arp_mac":
        device_sync_service.sync_arp_mac(device)
    elif scope == "logs":
        device_sync_service.sync_logs(device)
    elif scope == "all":
        device_sync_service.sync_core(device)
    else:
        raise ValueError(
            f"sync_device_task: scope inválido {scope!r} "
            "(esperado: vlans / ports / svis / global_config / arp_mac / logs / all)"
        )


@celery_app.task(name="ansiauth.device.search_mac")
def search_mac_task(device_name: str, pattern: str, job_id: str) -> None:
    from app.composition import device_repository, job_repository

    job = job_repository.get(job_id)
    if job is None:
        logger.warning("search_mac_task: job '%s' no existe, saltando", job_id)
        return
    device = device_repository.get(device_name)
    if device is None:
        job.marcar_fallido(f"Device '{device_name}' not found", False, None)
        job_repository.add(job)
        return
    job.marcar_iniciado()
    job_repository.add(job)
    try:
        entries = device.driver.search_mac_table(pattern, device, device.password)
        job.marcar_completado({"entries": entries, "pattern": pattern})
    except Exception as exc:
        job.marcar_fallido(str(exc), False, None)
    job_repository.add(job)


def encolar_sync(device_name: str, scope: str, countdown: int = 0) -> "tuple[str, bool]":
    from app.composition import redis_coordinator

    task_id = str(uuid.uuid4())
    existente = redis_coordinator.reservar_sync(device_name, scope, task_id)
    if existente is not None:
        logger.debug(
            "sync coalescing: device=%s scope=%s se une a la sync pendiente %s",
            device_name, scope, existente,
        )
        return existente, False
    try:
        sync_device_task.apply_async(args=[device_name, scope], countdown=countdown, task_id=task_id)
    except Exception:
        redis_coordinator.limpiar_sync_pendiente(device_name, scope)
        raise
    return task_id, True


def _encolar_sync_si_no_pendiente(device_name: str, scope: str, countdown: int = 0) -> bool:
    return encolar_sync(device_name, scope, countdown=countdown)[1]


@celery_app.task(name="ansiauth.device.sync_stale")
def sync_stale_devices_task() -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, or_

    from app.db.models import DeviceModel
    from app.db.session import get_session

    threshold = datetime.now(timezone.utc) - timedelta(seconds=SYNC_STALE_THRESHOLD_S)

    with get_session() as session:
        oldest_sync = func.coalesce(
            func.least(
                func.coalesce(DeviceModel.vlans_synced_at, datetime.min.replace(tzinfo=timezone.utc)),
                func.coalesce(DeviceModel.ports_synced_at, datetime.min.replace(tzinfo=timezone.utc)),
                func.coalesce(DeviceModel.svis_synced_at, datetime.min.replace(tzinfo=timezone.utc)),
            ),
            datetime.min.replace(tzinfo=timezone.utc),
        )
        rows = (
            session.query(DeviceModel.name)
            .filter(
                or_(
                    DeviceModel.vlans_synced_at.is_(None),
                    DeviceModel.ports_synced_at.is_(None),
                    DeviceModel.svis_synced_at.is_(None),
                    oldest_sync < threshold,
                )
            )
            .order_by(oldest_sync.asc())
            .all()
        )
        device_names = [name for (name,) in rows]

    if not device_names:
        logger.debug("sync_stale_devices_task: nothing to refresh")
        return

    encolados = 0
    for i, name in enumerate(device_names):
        countdown = i * SYNC_STALE_STAGGER_S
        if _encolar_sync_si_no_pendiente(name, "all", countdown=countdown):
            encolados += 1
    logger.info(
        "sync_stale_devices_task: candidates=%d enqueued=%d skipped_coalesced=%d",
        len(device_names), encolados, len(device_names) - encolados,
    )


@celery_app.task(name="ansiauth.jobs.recuperar_huerfanos")
def recuperar_huerfanos_task() -> None:
    from app.composition import job_repository, redis_coordinator
    from app.services.trabajos_huerfanos import recuperar_trabajos_huerfanos

    recuperar_trabajos_huerfanos(job_repository, redis_coordinator)
