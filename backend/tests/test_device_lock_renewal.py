from __future__ import annotations

import logging
import threading
import time

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import LockNotOwnedError

from app.services import redis_coordinator as rc
from app.services.redis_coordinator import RedisCoordinator


class _FakeLock:
    def __init__(self, acquire_ok=True, extend_errors=None):
        self.acquire_ok = acquire_ok
        self.extend_errors = list(extend_errors or [])
        self.acquire_args = None
        self.extends: list = []
        self.released = threading.Event()

    def acquire(self, blocking=True, blocking_timeout=None):
        self.acquire_args = (blocking, blocking_timeout)
        return self.acquire_ok

    def extend(self, additional_time, replace_ttl=False):
        assert not self.released.is_set(), "se renovo un candado ya liberado"
        self.extends.append((additional_time, replace_ttl))
        if self.extend_errors:
            error = self.extend_errors.pop(0)
            if error is not None:
                raise error
        return True

    def release(self):
        self.released.set()


class _FakeRedis:
    def __init__(self, lock):
        self.lock_obj = lock
        self.lock_kwargs = None
        self.lock_name = None

    def lock(self, name, **kwargs):
        self.lock_name, self.lock_kwargs = name, kwargs
        return self.lock_obj


class _Capturador(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.mensajes: list[str] = []

    def emit(self, record):
        self.mensajes.append(record.getMessage())


@pytest.fixture
def logs():
    handler = _Capturador()
    previo = (rc.logger.level, rc.logger.disabled)
    rc.logger.addHandler(handler)
    rc.logger.setLevel(logging.DEBUG)
    rc.logger.disabled = False
    yield handler
    rc.logger.removeHandler(handler)
    rc.logger.setLevel(previo[0])
    rc.logger.disabled = previo[1]


@pytest.fixture
def rapido(monkeypatch):
    monkeypatch.setattr(rc, "DEVICE_LOCK_TTL_S", 3)
    monkeypatch.setattr(rc, "DEVICE_LOCK_RENEW_S", 0.05)


def _coordinador(lock):
    coord = RedisCoordinator(redis_url="")
    fake = _FakeRedis(lock)
    coord._redis_client = fake
    return coord, fake


def test_el_candado_se_crea_con_vencimiento_corto_y_extensible_desde_otro_hilo(rapido):
    coord, fake = _coordinador(_FakeLock())
    with coord.bloquear("dev1"):
        pass
    assert fake.lock_name == "device_lock:dev1"
    assert fake.lock_kwargs == {"timeout": 3, "thread_local": False}


def test_valores_por_defecto_del_candado():
    assert rc.DEVICE_LOCK_TTL_S == 60
    assert rc.DEVICE_LOCK_RENEW_S == 20
    assert rc.DEVICE_LOCK_RENEW_S < rc.DEVICE_LOCK_TTL_S / 2
    assert rc.DEVICE_LOCK_WAIT_S == 600


def test_se_renueva_mientras_el_trabajo_corre(rapido):
    lock = _FakeLock()
    coord, _ = _coordinador(lock)
    with coord.bloquear("dev1"):
        time.sleep(0.35)
    assert len(lock.extends) >= 4
    assert all(ttl == 3 and replace for ttl, replace in lock.extends)


def test_deja_de_renovar_al_salir_y_antes_de_liberar(rapido):
    lock = _FakeLock()
    coord, _ = _coordinador(lock)
    with coord.bloquear("dev1"):
        time.sleep(0.2)
    assert lock.released.is_set()
    n = len(lock.extends)
    time.sleep(0.25)
    assert len(lock.extends) == n


def test_libera_y_deja_de_renovar_aunque_el_trabajo_falle(rapido):
    lock = _FakeLock()
    coord, _ = _coordinador(lock)
    with pytest.raises(RuntimeError):
        with coord.bloquear("dev1"):
            time.sleep(0.12)
            raise RuntimeError("fallo el trabajo")
    assert lock.released.is_set()
    n = len(lock.extends)
    time.sleep(0.2)
    assert len(lock.extends) == n


def test_si_pierde_el_candado_lo_registra_deja_de_renovar_y_no_corta_el_trabajo(rapido, logs):
    lock = _FakeLock(extend_errors=[None, LockNotOwnedError("vencio")])
    coord, _ = _coordinador(lock)
    with coord.bloquear("dev1"):
        time.sleep(0.4)
    assert len(lock.extends) == 2
    assert any("Device lock LOST device=dev1" in m for m in logs.mensajes)


def test_un_corte_transitorio_de_redis_no_frena_las_renovaciones(rapido, logs):
    lock = _FakeLock(extend_errors=[RedisConnectionError("caido"), None, None])
    coord, _ = _coordinador(lock)
    with coord.bloquear("dev1"):
        time.sleep(0.3)
    assert len(lock.extends) >= 3
    assert any("renewal failed device=dev1" in m for m in logs.mensajes)
    assert not any("LOST" in m for m in logs.mensajes)


def test_la_espera_por_defecto_tiene_tope(monkeypatch):
    monkeypatch.setattr(rc, "DEVICE_LOCK_WAIT_S", 123.0)
    lock = _FakeLock()
    coord, _ = _coordinador(lock)
    with coord.bloquear("dev1"):
        pass
    assert lock.acquire_args == (True, 123.0)


def test_timeout_none_espera_sin_limite_y_uno_explicito_se_respeta():
    lock = _FakeLock()
    coord, _ = _coordinador(lock)
    with coord.bloquear("dev1", timeout=None):
        pass
    assert lock.acquire_args == (True, None)
    lock2 = _FakeLock()
    coord2, _ = _coordinador(lock2)
    with coord2.bloquear("dev1", timeout=7):
        pass
    assert lock2.acquire_args == (True, 7)


def test_si_no_consigue_el_candado_falla_limpio_sin_renovar_ni_ejecutar(rapido):
    lock = _FakeLock(acquire_ok=False)
    coord, _ = _coordinador(lock)
    ejecutado = False
    with pytest.raises(TimeoutError, match="device busy"):
        with coord.bloquear("dev1", timeout=0.1):
            ejecutado = True
    time.sleep(0.15)
    assert not ejecutado and lock.extends == [] and not lock.released.is_set()


def test_sin_redis_el_tope_tambien_rige_en_el_candado_del_proceso():
    coord = RedisCoordinator(redis_url="")
    listo, soltar = threading.Event(), threading.Event()

    def ocupar():
        with coord.bloquear("dev1", timeout=None):
            listo.set()
            soltar.wait(5)

    t = threading.Thread(target=ocupar); t.start()
    assert listo.wait(2)
    try:
        with pytest.raises(TimeoutError, match="device busy"):
            with coord.bloquear("dev1", timeout=0.1):
                pass
    finally:
        soltar.set(); t.join()
