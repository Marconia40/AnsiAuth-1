from __future__ import annotations

import pytest

from app.composition import job_repository, plugin_registry, puerto_repository, svi_repository
from app.models.port import Puerto
from app.models.svi import SVI

from tests._puerto_fakes import FakePuertoDriver, get_or_create_device


def _p(**k) -> Puerto:
    return Puerto(interface="Gi0/1", device="d", **k)


@pytest.mark.parametrize("pedido, esperado", [
    (dict(description="uplink"), {"description": "uplink"}),
    (dict(description=""), {"description": None}),
    (dict(admin_up=False), {"admin_up": False}),
    (dict(access_vlan=44), {"access_vlan": 44}),
    (dict(poe_enabled=True), {"poe_enabled": True}),
    (dict(allowed_vlans=[30], allowed_vlan_operation="add"), {}),
    (dict(allowed_vlans=[30], allowed_vlan_operation="remove"), {}),
    (dict(allowed_vlans=[10, 20], allowed_vlan_operation="replace"), {"allowed_vlans": [10, 20]}),
    (dict(mode="trunk", access_vlan=10, allowed_vlans=[20, 10]),
     {"mode": "trunk", "access_vlan": 10, "allowed_vlans": [10, 20]}),
    (dict(mode="access", access_vlan=10), {"mode": "access", "access_vlan": 10, "allowed_vlans": None}),
    (dict(storm_control_enabled=True, storm_control_threshold=20, storm_control_action="filter", storm_control_trap=False),
     {"storm_control_enabled": True, "storm_control_threshold": 20, "storm_control_action": "filter",
      "storm_control_trap": False}),
    (dict(storm_control_enabled=False),
     {"storm_control_enabled": False, "storm_control_threshold": None, "storm_control_action": None,
      "storm_control_trap": None}),
    (dict(reset=True), {}),
])
def test_puerto_campos_de_cache(pedido, esperado):
    assert _p(**pedido).campos_de_cache() == esperado


@pytest.mark.parametrize("pedido, esperado", [
    (dict(description="wifi"), {"description": "wifi"}),
    (dict(description=""), {"description": None}),
    (dict(admin_up=False), {"admin_up": False}),
    (dict(ipv4_address="10.0.0.1/24"), {"ipv4_address": "10.0.0.1/24"}),
    (dict(acl_in=""), {"acl_in": None}),
    (dict(acl_out="X"), {"acl_out": "X"}),
    (dict(dhcp_relay_add="10.9.9.9"), {}),
    (dict(dhcp_relay_remove="10.9.9.9"), {}),
    (dict(ipv4_secondary_add="10.5.5.1/24"), {}),
    (dict(ipv4_secondary_remove="10.5.5.1/24"), {}),
    (dict(crear=True), None),
    (dict(eliminar=True), None),
])
def test_svi_campos_de_cache(pedido, esperado):
    assert SVI(vlan_id=10, device="d", **pedido).campos_de_cache() == esperado


_DEVICE = "trk_cache_dev"


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakePuertoDriver()
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    return drv


@pytest.fixture
def device(fake_driver):
    return get_or_create_device(_DEVICE, site_name="Tracking Cache Test Site")


def _fila_completa() -> Puerto:
    return Puerto(
        interface="GigabitEthernet0/0/24", device=_DEVICE, description="troncal", admin_up=True,
        operational_up=True, mode="trunk", access_vlan=10, allowed_vlans=[10, 20, 30],
        storm_control_enabled=True, storm_control_threshold=10.0,
    )


def test_actualizar_campos_solo_toca_lo_indicado(device):
    puerto_repository.add(_fila_completa())
    puerto_repository.actualizar_campos(
        Puerto(interface="GigabitEthernet0/0/24", device=_DEVICE), {"description": "nueva"},
    )
    fila = puerto_repository.get(("GigabitEthernet0/0/24", _DEVICE))
    assert fila.description == "nueva"
    assert (fila.mode, fila.access_vlan, fila.allowed_vlans, fila.admin_up, fila.operational_up) == (
        "trunk", 10, [10, 20, 30], True, True,
    )
    assert fila.storm_control_enabled is True and fila.storm_control_threshold == 10.0


def test_actualizar_campos_sin_fila_previa_se_comporta_como_add(device):
    nueva = Puerto(interface="GigabitEthernet0/0/40", device=_DEVICE, description="recien llegado")
    puerto_repository.actualizar_campos(nueva, {"description": "ignorado: no hay fila que preservar"})
    assert puerto_repository.get(("GigabitEthernet0/0/40", _DEVICE)).description == "recien llegado"


def test_actualizar_campos_en_svi(device):
    svi_repository.add(SVI(vlan_id=77, device=_DEVICE, description="a", ipv4_address="10.7.7.1/24", admin_up=True))
    svi_repository.actualizar_campos(SVI(vlan_id=77, device=_DEVICE), {"description": "b"})
    fila = svi_repository.get((77, _DEVICE))
    assert (fila.description, fila.ipv4_address, fila.admin_up) == ("b", "10.7.7.1/24", True)


@pytest.fixture
def sin_sync_posterior(monkeypatch):
    from app import tasks
    monkeypatch.setattr(tasks.sync_device_task, "delay", lambda *a, **k: None)


def test_un_remove_no_deja_la_fila_degradada(admin_client, device, fake_driver, sin_sync_posterior):
    puerto_repository.add(_fila_completa())
    res = admin_client.patch(
        f"/api/v1/devices/{_DEVICE}/ports/trunk-vlans",
        json={"interface": "GigabitEthernet0/0/24", "mode": "remove", "vlans": [30]},
    )
    assert res.status_code == 202, res.text
    assert job_repository.get(res.json()["data"]["jobs"][0]["job_id"]).status == "completed"
    fila = puerto_repository.get(("GigabitEthernet0/0/24", _DEVICE))
    assert fila.mode == "trunk" and fila.access_vlan == 10 and fila.admin_up is True
    assert fila.allowed_vlans == [10, 20, 30]


def test_un_cambio_de_descripcion_conserva_el_resto(admin_client, device, fake_driver, sin_sync_posterior):
    puerto_repository.add(_fila_completa())
    res = admin_client.patch(
        f"/api/v1/devices/{_DEVICE}/ports/description",
        json={"interface": "GigabitEthernet0/0/24", "description": "otro"},
    )
    assert res.status_code == 202, res.text
    fila = puerto_repository.get(("GigabitEthernet0/0/24", _DEVICE))
    assert fila.description == "otro"
    assert (fila.mode, fila.access_vlan, fila.allowed_vlans, fila.admin_up) == ("trunk", 10, [10, 20, 30], True)


def test_una_vlan_sigue_persistiendo_el_objeto_entero(admin_client, device, fake_driver, sin_sync_posterior):
    from app.composition import vlan_repository
    res = admin_client.post("/api/v1/vlans/", json={"vlan_id": 901, "name": "TRK-PARCIAL", "devices": [_DEVICE]})
    assert res.status_code == 202, res.text
    fila = vlan_repository.get((901, _DEVICE))
    assert fila is not None and fila.name == "TRK-PARCIAL"


def test_eliminar_una_vlan_borra_su_fila(admin_client, device, fake_driver, sin_sync_posterior):
    from app.composition import vlan_repository
    from app.models.vlan import VLAN
    vlan_repository.add(VLAN(vlan_id=902, name="A-BORRAR", device=_DEVICE))
    res = admin_client.request("DELETE", "/api/v1/vlans/902", json={"devices": [_DEVICE]})
    assert res.status_code == 202, res.text
    assert job_repository.get(res.json()["data"]["jobs"][0]["job_id"]).status == "completed"
    assert vlan_repository.get((902, _DEVICE)) is None


def test_quitar_borra_la_fila_de_la_entidad(device):
    svi_repository.add(SVI(vlan_id=78, device=_DEVICE, description="a"))
    svi_repository.quitar(SVI(vlan_id=78, device=_DEVICE, eliminar=True))
    assert svi_repository.get((78, _DEVICE)) is None
