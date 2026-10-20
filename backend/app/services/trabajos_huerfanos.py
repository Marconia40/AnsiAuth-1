from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ORPHAN_JOB_MIN_AGE_S: float = float(os.getenv("ORPHAN_JOB_MIN_AGE_S", "600"))


def recuperar_trabajos_huerfanos(job_repository, coordinador, ahora: "datetime | None" = None) -> int:
    ahora = ahora or datetime.now(timezone.utc)
    sin_redis = []

    def es_huerfano(job) -> bool:
        if job.started_at is not None:
            if (ahora - job.started_at).total_seconds() < ORPHAN_JOB_MIN_AGE_S:
                return False
        tomado = coordinador.bloqueo_en_redis(job.device) if job.device else False
        if tomado is None:
            sin_redis.append(job.job_id)
            return False
        return not tomado

    n = job_repository.recuperar_huerfanos(es_huerfano)
    if sin_redis:
        logger.warning(
            "Jobs huérfanos: Redis no responde, %d job(s) en running sin verificar", len(sin_redis),
        )
    if n:
        logger.info("Jobs huérfanos: %d marcado(s) como fallidos", n)
    return n
