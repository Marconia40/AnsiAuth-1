from __future__ import annotations

import pytest

from app.composition import puerto_repository
from app.models.port import Puerto

from tests._puerto_fakes import get_or_create_device

_DEVICE = "list_dev"


@pytest.fixture
def device():
    return get_or_create_device(_DEVICE, site_name="Ports List Test Site")


@pytest.fixture
def seeded_ports(device):
    ports = [
        Puerto(
            interface="GigabitEthernet0/0/1", device=_DEVICE, description="Workstation-01",
            admin_up=True, operational_up=True, mode="access", access_vlan=10,
        ),
        Puerto(
            interface="GigabitEthernet0/0/24", device=_DEVICE, description="Uplink",
            admin_up=True, operational_up=True, mode="trunk", access_vlan=1,
            allowed_vlans=[10, 20, 30],
        ),
    ]
    for p in ports:
        puerto_repository.add(p)
    return ports


def _url(name: str = _DEVICE) -> str:
    return f"/api/v1/devices/{name}/ports/"


def test_list_ports_returns_envelope(client, seeded_ports):
    res = client.get(_url())
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    payload = body["data"]["data"]
    assert payload["device"] == _DEVICE
    assert payload["count"] == len(payload["ports"])
    assert payload["count"] == 2
    assert isinstance(payload["ports"], list)
    for port in payload["ports"]:
        for key in (
            "name", "description", "admin_up", "operational_up", "mode",
            "access_vlan", "allowed_vlans", "storm_control_enabled",
            "storm_control_threshold", "storm_control_action", "storm_control_trap",
        ):
            assert key in port


def test_list_ports_no_rows_yet_returns_empty(client):
    dev = get_or_create_device("list_dev_empty", site_name="Ports List Test Site")
    res = client.get(_url(dev.name))
    assert res.status_code == 200
    payload = res.json()["data"]["data"]
    assert payload["count"] == 0
    assert payload["ports"] == []


def test_list_ports_unknown_device_returns_403(client):
    res = client.get(_url("__definitely_not_a_device__"))
    assert res.status_code == 403


def test_list_ports_observer_can_read(observer_client, seeded_ports):
    res = observer_client.get(_url())
    assert res.status_code == 200


def test_list_ports_operator_can_read(operator_client, seeded_ports):
    res = operator_client.get(_url())
    assert res.status_code == 200


def test_list_ports_unauthenticated_rejected(unauth_client, seeded_ports):
    res = unauth_client.get(_url())
    assert res.status_code == 401


def test_response_model_includes_unknown_fields_as_null(client, seeded_ports):
    res = client.get(_url())
    payload = res.json()["data"]["data"]
    port_without_storm = next(p for p in payload["ports"] if p["mode"] == "access")
    assert port_without_storm["storm_control_enabled"] is None
    assert port_without_storm["storm_control_threshold"] is None


def test_response_includes_sync_metadata(client, seeded_ports):
    res = client.get(_url())
    data = res.json()["data"]
    assert "synced_at" in data
    assert "sync_error" in data
    assert "sync_in_progress" in data
