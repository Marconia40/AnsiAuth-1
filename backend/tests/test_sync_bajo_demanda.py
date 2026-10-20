from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import DeviceModel
from app.db.session import get_session


def test_barrido_periodico_apagado_por_defecto(monkeypatch):
    from app.worker import agenda_periodica

    monkeypatch.delenv("SYNC_PERIODIC_ENABLED", raising=False)
    assert "sync-stale-devices" not in agenda_periodica()


def test_barrido_periodico_se_puede_habilitar(monkeypatch):
    from app.worker import agenda_periodica

    monkeypatch.setenv("SYNC_PERIODIC_ENABLED", "true")
    assert "sync-stale-devices" in agenda_periodica()


@pytest.fixture()
def equipo():
    from app.composition import device_repository, inventory, site_repository

    nombre = "bajo_demanda_dev"
    if device_repository.get(nombre) is None:
        try:
            site = site_repository.crear_con_grupo_default("Bajo Demanda Site", kind="REGULAR")
        except ValueError:
            site = site_repository.list(name="Bajo Demanda Site")[0]
        inventory.register(
            name=nombre, host="10.92.0.1", vendor="cisco_ios", platform="ios",
            username="admin", password="admin123", site_id=site.id,
            device_group_id=None, actor={"username": "test-setup"},
        )
    return nombre


@pytest.fixture()
def encoladas(monkeypatch):
    from app import tasks

    lista: list = []
    monkeypatch.setattr(
        tasks, "encolar_sync",
        lambda device_name, scope, countdown=0: (lista.append((device_name, scope)), ("t", True))[1],
    )
    return lista


def _sincronizado_hace(nombre: str, minutos: int) -> None:
    momento = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    with get_session() as session:
        session.query(DeviceModel).filter_by(name=nombre).update({
            DeviceModel.vlans_synced_at: momento,
            DeviceModel.ports_synced_at: momento,
            DeviceModel.svis_synced_at: momento,
        })


def test_al_abrir_no_relee_un_equipo_sincronizado_hace_10_minutos(equipo, encoladas, admin_client):
    _sincronizado_hace(equipo, 10)
    r = admin_client.post("/api/v1/dashboard/refresh", params={"scope": "device", "name": equipo})
    assert r.status_code == 202, r.text
    assert encoladas == []


def test_al_abrir_relee_un_equipo_sincronizado_hace_20_minutos(equipo, encoladas, admin_client):
    _sincronizado_hace(equipo, 20)
    r = admin_client.post("/api/v1/dashboard/refresh", params={"scope": "device", "name": equipo})
    assert r.status_code == 202, r.text
    assert encoladas == [(equipo, "all")]
