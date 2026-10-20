import os

import pytest

from app.services.redis_coordinator import RedisCoordinator


def _fresh_coordinator_no_redis() -> RedisCoordinator:
    return RedisCoordinator(redis_url="")


def test_coalescing_no_redis_never_reports_pending():
    coord = _fresh_coordinator_no_redis()
    assert coord.hay_sync_pendiente("dev-1", "all") is False
    coord.marcar_sync_pendiente("dev-1", "all")
    assert coord.hay_sync_pendiente("dev-1", "all") is False
    coord.limpiar_sync_pendiente("dev-1", "all")


@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="Redis-path test requires REDIS_URL",
)
def test_coalescing_marks_then_detects_then_clears():
    coord = RedisCoordinator()
    r = coord._get_redis()
    assert r is not None
    r.delete("sync_pending:dev-t1:all")

    assert coord.hay_sync_pendiente("dev-t1", "all") is False
    coord.marcar_sync_pendiente("dev-t1", "all", ttl_s=60)
    assert coord.hay_sync_pendiente("dev-t1", "all") is True

    assert coord.hay_sync_pendiente("dev-t1", "vlans") is False

    coord.limpiar_sync_pendiente("dev-t1", "all")
    assert coord.hay_sync_pendiente("dev-t1", "all") is False


@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="Redis-path test requires REDIS_URL",
)
def test_coalescing_marker_ttl_expires():
    import time

    coord = RedisCoordinator()
    r = coord._get_redis()
    assert r is not None
    r.delete("sync_pending:dev-t2:all")

    coord.marcar_sync_pendiente("dev-t2", "all", ttl_s=1)
    assert coord.hay_sync_pendiente("dev-t2", "all") is True
    time.sleep(1.5)
    assert coord.hay_sync_pendiente("dev-t2", "all") is False


@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="Redis-path test requires REDIS_URL",
)
def test_coalescing_isolated_per_device():
    coord = RedisCoordinator()
    r = coord._get_redis()
    assert r is not None
    r.delete("sync_pending:dev-a:all")
    r.delete("sync_pending:dev-b:all")

    coord.marcar_sync_pendiente("dev-a", "all")
    assert coord.hay_sync_pendiente("dev-a", "all") is True
    assert coord.hay_sync_pendiente("dev-b", "all") is False

    coord.limpiar_sync_pendiente("dev-a", "all")


def test_reservar_sync_no_redis_never_coalesces():
    coord = _fresh_coordinator_no_redis()
    assert coord.reservar_sync("dev-1", "all", "t1") is None
    assert coord.reservar_sync("dev-1", "all", "t2") is None


@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="Redis-path test requires REDIS_URL",
)
def test_reservar_sync_devuelve_la_pendiente_hasta_que_arranca():
    coord = RedisCoordinator()
    coord.limpiar_sync_pendiente("dev-r1", "vlans")

    assert coord.reservar_sync("dev-r1", "vlans", "t1") is None
    assert coord.reservar_sync("dev-r1", "vlans", "t2") == "t1"
    assert coord.reservar_sync("dev-r1", "ports", "t3") is None

    coord.limpiar_sync_pendiente("dev-r1", "vlans")
    assert coord.reservar_sync("dev-r1", "vlans", "t4") is None
    coord.limpiar_sync_pendiente("dev-r1", "vlans")
    coord.limpiar_sync_pendiente("dev-r1", "ports")


class _CoordinadorEnMemoria:
    def __init__(self):
        self.marcas: dict = {}

    def reservar_sync(self, device_name, scope, task_id, ttl_s=300):
        clave = (device_name, scope)
        if clave in self.marcas:
            return self.marcas[clave]
        self.marcas[clave] = task_id
        return None

    def limpiar_sync_pendiente(self, device_name, scope):
        self.marcas.pop((device_name, scope), None)


@pytest.fixture()
def cola_falsa(monkeypatch):
    import app.composition as composition
    from app import tasks

    coord = _CoordinadorEnMemoria()
    encoladas: list = []
    monkeypatch.setattr(composition, "redis_coordinator", coord)
    monkeypatch.setattr(
        tasks.sync_device_task, "apply_async",
        lambda args, countdown=0, task_id=None: encoladas.append((tuple(args), task_id)),
    )
    return coord, encoladas


def test_encolar_sync_se_une_a_la_pendiente(cola_falsa):
    from app.tasks import encolar_sync

    coord, encoladas = cola_falsa
    id1, nueva1 = encolar_sync("dev-x", "all")
    id2, nueva2 = encolar_sync("dev-x", "all")

    assert (nueva1, nueva2) == (True, False)
    assert id2 == id1
    assert encoladas == [(("dev-x", "all"), id1)]

    coord.limpiar_sync_pendiente("dev-x", "all")
    id3, nueva3 = encolar_sync("dev-x", "all")
    assert nueva3 is True and id3 != id1
    assert len(encoladas) == 2


def test_encolar_sync_libera_la_reserva_si_el_broker_falla(cola_falsa, monkeypatch):
    from app import tasks

    coord, _ = cola_falsa

    def _broker_caido(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.sync_device_task, "apply_async", _broker_caido)
    with pytest.raises(ConnectionError):
        tasks.encolar_sync("dev-y", "vlans")
    assert coord.marcas == {}


@pytest.fixture()
def equipo_registrado():
    from app.composition import device_repository, inventory, site_repository

    nombre = "coalesce_dev"
    if device_repository.get(nombre) is None:
        try:
            site = site_repository.crear_con_grupo_default("Coalescing Test Site", kind="REGULAR")
        except ValueError:
            site = site_repository.list(name="Coalescing Test Site")[0]
        inventory.register(
            name=nombre, host="10.91.0.1", vendor="cisco_ios", platform="ios",
            username="admin", password="admin123", site_id=site.id,
            device_group_id=None, actor={"username": "test-setup"},
        )
    return nombre


def test_refresh_manual_repetido_se_une_a_la_misma_sync(equipo_registrado, cola_falsa, admin_client):
    _, encoladas = cola_falsa
    r1 = admin_client.post(f"/api/v1/devices/{equipo_registrado}/vlans/refresh")
    r2 = admin_client.post(f"/api/v1/devices/{equipo_registrado}/vlans/refresh")
    assert r1.status_code == 202, r1.text
    assert r2.status_code == 202, r2.text
    assert r1.json()["data"]["task_id"] == r2.json()["data"]["task_id"]
    assert len(encoladas) == 1
