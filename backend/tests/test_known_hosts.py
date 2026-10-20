import subprocess

import pytest

from app.services import known_hosts

_CLAVE = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


@pytest.fixture
def archivos(tmp_path, monkeypatch):
    directo = tmp_path / "known_hosts_directo"
    ansible = tmp_path / "known_hosts"
    monkeypatch.setattr(known_hosts, "KNOWN_HOSTS_DIRECTO", str(directo))
    monkeypatch.setattr(known_hosts, "KNOWN_HOSTS_ANSIBLE", str(ansible))
    return directo, ansible


def test_olvida_el_host_en_los_dos_archivos_y_deja_los_demas(archivos):
    directo, ansible = archivos
    directo.write_text(f"sw1 ssh-ed25519 {_CLAVE}\nsw2 ssh-ed25519 {_CLAVE}\n")
    ansible.write_text(f"sw1 ssh-ed25519 {_CLAVE}\n")

    olvidados = known_hosts.olvidar("sw1")

    assert set(olvidados) == {str(directo), str(ansible)}
    assert "sw1 " not in directo.read_text()
    assert "sw2 " in directo.read_text()
    assert "sw1 " not in ansible.read_text()
    assert not (directo.parent / "known_hosts_directo.old").exists()


def test_olvida_entradas_hasheadas(archivos):
    directo, _ = archivos
    directo.write_text(f"sw1 ssh-ed25519 {_CLAVE}\n")
    subprocess.run(["ssh-keygen", "-H", "-f", str(directo)], check=True, capture_output=True)
    assert "sw1" not in directo.read_text()

    assert known_hosts.olvidar("sw1") == [str(directo)]
    assert directo.read_text().strip() == ""


def test_host_desconocido_o_sin_archivos_no_lanza(archivos):
    assert known_hosts.olvidar("sw1") == []
    directo, _ = archivos
    directo.write_text(f"sw2 ssh-ed25519 {_CLAVE}\n")
    assert known_hosts.olvidar("sw1") == []
    assert "sw2 " in directo.read_text()
