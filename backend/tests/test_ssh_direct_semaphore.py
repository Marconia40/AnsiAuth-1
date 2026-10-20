from __future__ import annotations

import contextlib
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import redis_coordinator as rc_module
from app.services import ssh_direct_service as ssh
from app.services.redis_coordinator import RedisCoordinator


def _equipo(host="10.0.0.1"):
    return SimpleNamespace(name=f"sw-{host}", host=host, username="u", vendor="cisco_ios")


def _ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\nexit\n", stderr="")


class _SlotRegistrado:
    def __init__(self):
        self.dentro = False
        self.tomados = 0

    @contextlib.contextmanager
    def adquirir_slot(self):
        self.tomados += 1
        self.dentro = True
        try:
            yield "slot"
        finally:
            self.dentro = False


@pytest.fixture(autouse=True)
def _sin_agente_ni_aprendizaje(monkeypatch):
    ssh._ALGORITMOS_APRENDIDOS.clear()
    monkeypatch.setattr(ssh, "_agent_for", lambda device: contextlib.nullcontext({}))
    yield
    ssh._ALGORITMOS_APRENDIDOS.clear()


@pytest.fixture
def slot(monkeypatch):
    registro = _SlotRegistrado()
    monkeypatch.setattr("app.composition.redis_coordinator", registro)
    return registro


def test_la_sesion_directa_corre_dentro_de_un_slot(monkeypatch, slot):
    dentro_durante_ssh = []

    def _paced(cmd, lines, env, terminador):
        dentro_durante_ssh.append(slot.dentro)
        return _ok()

    monkeypatch.setattr(ssh, "_run_ssh_paced", _paced)

    rc, _, _, _ = ssh._run_ssh_interactive(_equipo(), ["show vlan"])

    assert rc == 0
    assert dentro_durante_ssh == [True]
    assert slot.tomados == 1
    assert slot.dentro is False


def test_un_solo_slot_aunque_haya_reintentos_de_negociacion(monkeypatch, slot):
    respuestas = iter([
        subprocess.CompletedProcess(
            args=[], returncode=255, stdout="",
            stderr="Unable to negotiate with 10.0.0.1 port 22: no matching key exchange "
                   "method found. Their offer: diffie-hellman-group14-sha1",
        ),
        _ok(),
    ])
    monkeypatch.setattr(ssh, "_run_ssh_paced", lambda *a, **k: next(respuestas))

    rc, _, _, _ = ssh._run_ssh_interactive(_equipo(), ["show vlan"])

    assert rc == 0
    assert slot.tomados == 1


def test_el_slot_se_libera_si_ssh_falla(monkeypatch, slot):
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=60)

    monkeypatch.setattr(ssh, "_run_ssh_paced", _timeout)

    rc, _, err, _ = ssh._run_ssh_interactive(_equipo(), ["show vlan"])

    assert rc == 1
    assert "timed out" in err
    assert slot.tomados == 1
    assert slot.dentro is False


def test_ansible_y_ssh_directo_comparten_el_mismo_techo(monkeypatch):
    monkeypatch.setattr(rc_module, "MAX_CONCURRENT_SSH", 1)
    coord = RedisCoordinator(redis_url="")
    monkeypatch.setattr("app.composition.redis_coordinator", coord)

    inicio_ssh = []
    monkeypatch.setattr(
        ssh, "_run_ssh_paced",
        lambda *a, **k: (inicio_ssh.append(time.monotonic()), _ok())[1],
    )

    ansible_tomo = threading.Event()
    liberar_ansible = threading.Event()

    def _ejecucion_ansible():
        with coord.adquirir_slot():
            ansible_tomo.set()
            liberar_ansible.wait(timeout=5)

    t_ansible = threading.Thread(target=_ejecucion_ansible)
    t_ansible.start()
    assert ansible_tomo.wait(timeout=5)

    resultado = {}
    t_ssh = threading.Thread(
        target=lambda: resultado.setdefault("rc", ssh._run_ssh_interactive(_equipo(), ["show vlan"])[0])
    )
    t_ssh.start()
    time.sleep(0.3)
    assert inicio_ssh == []

    liberado = time.monotonic()
    liberar_ansible.set()
    t_ansible.join(timeout=5)
    t_ssh.join(timeout=5)

    assert resultado["rc"] == 0
    assert len(inicio_ssh) == 1 and inicio_ssh[0] >= liberado
