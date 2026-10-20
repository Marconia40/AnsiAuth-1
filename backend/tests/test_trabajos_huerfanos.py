from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.job import Job
from app.services import trabajos_huerfanos
from app.services.trabajos_huerfanos import recuperar_trabajos_huerfanos

AHORA = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


class _Coordinador:
    def __init__(self, bloqueados=(), sin_redis=False):
        self.bloqueados = set(bloqueados)
        self.sin_redis = sin_redis

    def bloqueo_en_redis(self, device_id):
        if self.sin_redis:
            return None
        return device_id in self.bloqueados


@pytest.fixture
def repo():
    from app.composition import job_repository

    return job_repository


def _en_ejecucion(repo, device, hace_s):
    job = Job(playbook="test.yml", device=device)
    job.marcar_iniciado()
    job.started_at = AHORA - timedelta(seconds=hace_s)
    repo.add(job)
    return job


def _viejo():
    return trabajos_huerfanos.ORPHAN_JOB_MIN_AGE_S + 60


def test_job_sin_bloqueo_y_viejo_pasa_a_fallido(repo):
    job = _en_ejecucion(repo, "sw-caido", _viejo())

    recuperar_trabajos_huerfanos(repo, _Coordinador(), ahora=AHORA)

    recuperado = repo.get(job.job_id)
    assert recuperado.status == "failed"
    assert recuperado.error == "Unexpected termination"


def test_job_con_bloqueo_vigente_no_se_toca(repo):
    job = _en_ejecucion(repo, "sw-vivo", _viejo())

    recuperar_trabajos_huerfanos(repo, _Coordinador(bloqueados={"sw-vivo"}), ahora=AHORA)

    assert repo.get(job.job_id).status == "running"


def test_job_reciente_sin_bloqueo_no_se_toca(repo):
    job = _en_ejecucion(repo, "sw-reciente", 30)

    recuperar_trabajos_huerfanos(repo, _Coordinador(), ahora=AHORA)

    assert repo.get(job.job_id).status == "running"


def test_sin_redis_no_se_marca_nada(repo):
    job = _en_ejecucion(repo, "sw-incierto", _viejo())

    recuperar_trabajos_huerfanos(repo, _Coordinador(sin_redis=True), ahora=AHORA)

    assert repo.get(job.job_id).status == "running"


def test_solo_se_recuperan_los_huerfanos(repo):
    caido = _en_ejecucion(repo, "sw-a", _viejo())
    vivo = _en_ejecucion(repo, "sw-b", _viejo())

    n = recuperar_trabajos_huerfanos(repo, _Coordinador(bloqueados={"sw-b"}), ahora=AHORA)

    assert n >= 1
    assert repo.get(caido.job_id).status == "failed"
    assert repo.get(vivo.job_id).status == "running"


def test_el_barrido_periodico_esta_siempre_agendado(monkeypatch):
    from app.worker import agenda_periodica

    monkeypatch.delenv("SYNC_PERIODIC_ENABLED", raising=False)
    agenda = agenda_periodica()

    assert agenda["recuperar-jobs-huerfanos"]["task"] == "ansiauth.jobs.recuperar_huerfanos"


def test_bloqueo_en_redis_sin_redis_devuelve_none():
    from app.services.redis_coordinator import RedisCoordinator

    assert RedisCoordinator(redis_url="").bloqueo_en_redis("sw-x") is None
