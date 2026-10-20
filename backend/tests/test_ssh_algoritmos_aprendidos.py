from __future__ import annotations

import contextlib
import subprocess
from types import SimpleNamespace

import pytest

from app.services import ssh_direct_service as ssh


@pytest.fixture(autouse=True)
def _sin_aprendizaje_previo(monkeypatch):
    ssh._ALGORITMOS_APRENDIDOS.clear()
    monkeypatch.setattr(ssh, "_agent_for", lambda device: contextlib.nullcontext({}))
    yield
    ssh._ALGORITMOS_APRENDIDOS.clear()


def _equipo(host="10.0.0.1"):
    return SimpleNamespace(name=f"sw-{host}", host=host, username="u", vendor="cisco_ios")


def _primera_opcion(cmd, nombre):
    for i, parte in enumerate(cmd):
        if parte == "-o" and cmd[i + 1].startswith(f"{nombre}="):
            return cmd[i + 1].split("=", 1)[1]
    return None


def _equipo_legacy(monkeypatch, exige):
    llamadas = []
    categorias = {
        "KexAlgorithms": "key exchange method",
        "HostKeyAlgorithms": "host key type",
        "Ciphers": "cipher",
    }

    def _run_ssh_paced(cmd, lines, env, terminador="quit"):
        llamadas.append(cmd)
        for opcion, valor in exige.items():
            if _primera_opcion(cmd, opcion) != f"+{valor}":
                stderr = f"Unable to negotiate: no matching {categorias[opcion]} found. Their offer: {valor}"
                return subprocess.CompletedProcess(cmd, 255, "", stderr)
        return subprocess.CompletedProcess(cmd, 0, "salida", "")

    monkeypatch.setattr(ssh, "_run_ssh_paced", _run_ssh_paced)
    return llamadas


LEGACY = {"KexAlgorithms": "diffie-hellman-group1-sha1", "HostKeyAlgorithms": "ssh-rsa", "Ciphers": "aes128-cbc"}


def test_la_segunda_sesion_no_repite_la_negociacion(monkeypatch):
    llamadas = _equipo_legacy(monkeypatch, LEGACY)
    equipo = _equipo()

    rc, _, _, _ = ssh._run_ssh_interactive(equipo, ["show vlan"])
    assert rc == 0
    assert len(llamadas) == 4

    rc, _, _, _ = ssh._run_ssh_interactive(equipo, ["show vlan"])
    assert rc == 0
    assert len(llamadas) == 5


def test_lo_aprendido_es_por_equipo(monkeypatch):
    llamadas = _equipo_legacy(monkeypatch, LEGACY)
    ssh._run_ssh_interactive(_equipo("10.0.0.1"), ["show vlan"])
    ssh._run_ssh_interactive(_equipo("10.0.0.2"), ["show vlan"])
    assert len(llamadas) == 8


def test_algoritmo_aprendido_que_dejo_de_servir_se_reemplaza(monkeypatch):
    ssh._recordar_algoritmos("10.0.0.1", ["-o", "KexAlgorithms=+kex-viejo"])
    llamadas = _equipo_legacy(monkeypatch, {"KexAlgorithms": "kex-nuevo"})
    equipo = _equipo()

    rc, _, _, _ = ssh._run_ssh_interactive(equipo, ["show vlan"])
    assert rc == 0
    assert len(llamadas) == 2
    assert "KexAlgorithms=+kex-viejo" not in llamadas[-1]
    assert ssh._algoritmos_aprendidos("10.0.0.1") == ["-o", "KexAlgorithms=+kex-nuevo"]


def test_equipo_moderno_no_guarda_nada(monkeypatch):
    llamadas = _equipo_legacy(monkeypatch, {})
    ssh._run_ssh_interactive(_equipo(), ["show vlan"])
    assert len(llamadas) == 1
    assert ssh._algoritmos_aprendidos("10.0.0.1") == []


def test_si_la_negociacion_falla_igual_se_olvida_lo_aprendido(monkeypatch):
    ssh._recordar_algoritmos("10.0.0.1", ["-o", "Ciphers=+aes128-cbc"])

    def _run_ssh_paced(cmd, lines, env, terminador="quit"):
        stderr = "Unable to negotiate: no matching cipher found. Their offer: 3des-cbc"
        return subprocess.CompletedProcess(cmd, 255, "", stderr)

    monkeypatch.setattr(ssh, "_run_ssh_paced", _run_ssh_paced)
    rc, _, _, _ = ssh._run_ssh_interactive(_equipo(), ["show vlan"])
    assert rc == 255
    assert ssh._algoritmos_aprendidos("10.0.0.1") == []
