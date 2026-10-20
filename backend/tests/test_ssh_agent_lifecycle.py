import os
import shutil
import subprocess

import pytest

from app.services import ssh_direct_service as sds

pytestmark = pytest.mark.skipif(
    not all(shutil.which(b) for b in ("ssh-agent", "ssh-add", "ssh-keygen")),
    reason="OpenSSH client tools not installed",
)


def _clave_valida(tmp_path) -> str:
    path = tmp_path / "id_test"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
    return path.read_text()


def _zombies_propios() -> int:
    n = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/status") as f:
                st = dict(line.split(":", 1) for line in f if ":" in line)
        except OSError:
            continue
        if st.get("PPid", "").strip() == str(os.getpid()) and st.get("State", "").strip().startswith("Z"):
            n += 1
    return n


def test_agente_carga_la_clave_y_se_cosecha_al_terminar(tmp_path):
    keyfile = sds.write_private_key_file("dev-test", _clave_valida(tmp_path))
    env, proc = sds._start_agent(keyfile)
    listado = subprocess.run(["ssh-add", "-l"], env=env, capture_output=True, text=True)
    assert listado.returncode == 0 and "ED25519" in listado.stdout
    assert not os.path.exists(keyfile)
    sock_dir = os.path.dirname(env["SSH_AUTH_SOCK"])

    sds._stop_agent(env, proc)
    assert proc.returncode is not None
    assert not os.path.exists(sock_dir)


def test_clave_invalida_falla_con_mensaje_claro_y_sin_dejar_procesos(tmp_path):
    keyfile = sds.write_private_key_file("dev-test", "esto no es una clave privada")
    antes = _zombies_propios()
    with pytest.raises(RuntimeError, match="Could not load the device's private key"):
        sds._start_agent(keyfile)
    assert not os.path.exists(keyfile)
    assert _zombies_propios() == antes


def test_muchas_sesiones_no_acumulan_zombies(tmp_path):
    clave = _clave_valida(tmp_path)
    antes = _zombies_propios()
    for _ in range(25):
        env, proc = sds._start_agent(sds.write_private_key_file("dev-test", clave))
        sds._stop_agent(env, proc)
    assert _zombies_propios() == antes
