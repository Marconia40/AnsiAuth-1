from __future__ import annotations

import pytest

from app.composition import device_repository, job_repository, plugin_registry, user_repository
from app.db.models import DeviceGroupModel, DeviceModel, RoleAssignmentModel, SiteModel, UserModel
from app.db.session import get_session
from app.models.device import Device

from tests._puerto_fakes import FakePuertoDriver, StubUnimplementedDriver, get_or_create_device, get_or_create_site

_DEVICE = "wr_dev"
_IFACE = "GigabitEthernet0/0/1"


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakePuertoDriver()
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    return drv


@pytest.fixture
def device(fake_driver):
    return get_or_create_device(_DEVICE, site_name="Port Write API Test Site")


def _u(path: str, name: str = _DEVICE) -> str:
    return f"/api/v1/devices/{name}/ports/{path}"


_TEST_USER_ROLES: dict[str, str] = {}


def _ensure_user(username: str, role: str = "operator") -> None:
    _TEST_USER_ROLES[username] = role
    if user_repository.obtener_por_username(username) is None:
        is_sys = role in {"admin", "super-admin"}
        user_repository.crear(username, "p@ssword_99", is_system_admin=is_sys)


def _grant_site(username: str, site_ids: list[int]) -> None:
    role = _TEST_USER_ROLES.get(username, "operator")
    with get_session() as session:
        row = session.query(UserModel).filter_by(username=username).first()
        assert row is not None
        session.query(RoleAssignmentModel).filter(
            RoleAssignmentModel.user_id == row.id,
            RoleAssignmentModel.device_group_id.is_(None),
        ).delete(synchronize_session=False)
        for sid in site_ids:
            session.add(RoleAssignmentModel(user_id=row.id, site_id=sid, device_group_id=None, role=role))


def _attach_device_to_site(device_name: str, site_id: int) -> None:
    with get_session() as session:
        dev = session.query(DeviceModel).filter_by(name=device_name).first()
        assert dev is not None, f"Device '{device_name}' not in DB"
        row = session.query(SiteModel).filter_by(id=site_id).first()
        assert row is not None and row.default_group_id is not None
        dev.device_group_id = row.default_group_id


def _client(role: str, username: str | None = None):
    from app.core.security import create_access_token
    from fastapi.testclient import TestClient
    from app.main import app

    sub = username or role
    is_system_admin = role in {"admin", "super-admin"}
    token = create_access_token({"sub": sub, "is_system_admin": is_system_admin})
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_shutdown_requires_auth(unauth_client, device):
    res = unauth_client.post(_u("shutdown"), json={"interface": _IFACE})
    assert res.status_code == 401


def test_enable_requires_auth(unauth_client, device):
    res = unauth_client.post(_u("enable"), json={"interface": _IFACE})
    assert res.status_code == 401


def test_batch_requires_auth(unauth_client, device):
    res = unauth_client.post(_u("batch"), json={"changes": [{"interface": _IFACE, "description": "x"}]})
    assert res.status_code == 401


def test_invalid_token_rejected(device):
    c = _client("operator")
    c.headers.update({"Authorization": "Bearer not.a.valid.token"})
    res = c.post(_u("shutdown"), json={"interface": _IFACE})
    assert res.status_code == 401


def test_shutdown_observer_forbidden(observer_client, device):
    res = observer_client.post(_u("shutdown"), json={"interface": _IFACE})
    assert res.status_code == 403


def test_enable_observer_forbidden(observer_client, device):
    res = observer_client.post(_u("enable"), json={"interface": _IFACE})
    assert res.status_code == 403


def test_batch_observer_forbidden(observer_client, device):
    res = observer_client.post(_u("batch"), json={"changes": [{"interface": _IFACE, "description": "x"}]})
    assert res.status_code == 403


def test_shutdown_403_device_outside_allowed_sites(fake_driver):
    _ensure_user("site_op_sht")
    site_a = get_or_create_site("Site-A-sht")
    site_b = get_or_create_site("Site-B-sht")
    dev = get_or_create_device("wr_dev_sht", site_name="Site-B-sht")
    _attach_device_to_site(dev.name, site_b.id)
    _grant_site("site_op_sht", [site_a.id])

    res = _client("operator", "site_op_sht").post(_u("shutdown", dev.name), json={"interface": _IFACE})
    assert res.status_code in (403, 404)


def test_shutdown_200_device_in_allowed_site(fake_driver):
    _ensure_user("site_op_ok")
    site = get_or_create_site("Site-OK-sht")
    dev = get_or_create_device("wr_dev_ok", site_name="Site-OK-sht")
    _attach_device_to_site(dev.name, site.id)
    _grant_site("site_op_ok", [site.id])

    res = _client("operator", "site_op_ok").post(_u("shutdown", dev.name), json={"interface": _IFACE})
    assert res.status_code == 202, res.text


def test_admin_bypasses_site_scope(fake_driver):
    site = get_or_create_site("Site-Admin-bypass-wr")
    dev = get_or_create_device("wr_dev_admin_bypass", site_name="Site-Admin-bypass-wr")
    _attach_device_to_site(dev.name, site.id)
    res = _client("admin").post(_u("shutdown", dev.name), json={"interface": _IFACE})
    assert res.status_code == 202, res.text


def test_shutdown_404_unknown_device(operator_client, fake_driver):
    res = operator_client.post(_u("shutdown", "ghost-device"), json={"interface": _IFACE})
    assert res.status_code == 404


def test_enable_404_unknown_device(operator_client, fake_driver):
    res = operator_client.post(_u("enable", "ghost-device"), json={"interface": _IFACE})
    assert res.status_code == 404


def test_shutdown_422_missing_interface(operator_client, device):
    res = operator_client.post(_u("shutdown"), json={})
    assert res.status_code == 422


def test_batch_422_no_changes(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": []})
    assert res.status_code == 422


def test_batch_422_entry_with_no_fields(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [{"interface": _IFACE}]})
    assert res.status_code == 422


def test_access_mode_400_reserved_vlan(operator_client, device):
    res = operator_client.post(_u("access-mode"), json={"interface": _IFACE, "access_vlan": 1003})
    assert res.status_code == 422


@pytest.fixture
def huawei_device(fake_driver):
    return get_or_create_device("wr_dev_huawei", site_name="Port Write API Test Site", vendor="huawei_vrp")


def test_poe_422_rejected_on_cisco_aggregate(operator_client, device):
    res = operator_client.patch(_u("poe"), json={"interface": "Po1", "enabled": True})
    assert res.status_code == 422
    assert "PoE" in res.json()["message"]


def test_poe_422_rejected_on_huawei_aggregate(operator_client, huawei_device):
    res = operator_client.patch(_u("poe", "wr_dev_huawei"), json={"interface": "Eth-Trunk2", "enabled": True})
    assert res.status_code == 422
    assert "PoE" in res.json()["message"]


def test_storm_control_422_rejected_on_cisco_aggregate(operator_client, device):
    res = operator_client.patch(
        _u("storm-control"),
        json={"interface": "Po1", "enabled": True, "threshold_percent": 10},
    )
    assert res.status_code == 422
    assert "Storm-control" in res.json()["message"]


def test_storm_control_422_rejected_on_huawei_aggregate(operator_client, huawei_device):
    res = operator_client.patch(
        _u("storm-control", "wr_dev_huawei"),
        json={"interface": "Eth-Trunk2", "enabled": True, "threshold_percent": 10},
    )
    assert res.status_code == 422
    assert "Storm-control" in res.json()["message"]


def test_poe_202_allowed_on_physical_port(operator_client, device):
    res = operator_client.patch(_u("poe"), json={"interface": _IFACE, "enabled": True})
    assert res.status_code == 202


def test_batch_422_poe_rejected_on_aggregate(operator_client, device):
    res = operator_client.post(
        _u("batch"), json={"changes": [{"interface": "Po1", "poe_enabled": True}]},
    )
    assert res.status_code == 422
    assert "PoE" in res.json()["message"]


def test_batch_202_description_allowed_on_aggregate(operator_client, device):
    res = operator_client.post(
        _u("batch"), json={"changes": [{"interface": "Po1", "description": "core LAG"}]},
    )
    assert res.status_code == 202


def test_batch_422_dos_entradas_de_allowed_vlans_de_la_misma_interfaz(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _IFACE, "allowed_vlans": [10], "allowed_vlan_operation": "remove"},
        {"interface": _IFACE, "allowed_vlans": [20], "allowed_vlan_operation": "remove"},
    ]})
    assert res.status_code == 422
    assert "single entry" in res.json()["message"]


def test_batch_422_mode_trunk_mas_allowed_vlans_de_la_misma_interfaz(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _IFACE, "mode": "trunk", "access_vlan": 1, "allowed_vlans": [10, 20]},
        {"interface": _IFACE, "allowed_vlans": [30], "allowed_vlan_operation": "add"},
    ]})
    assert res.status_code == 422


def test_batch_202_allowed_vlans_de_interfaces_distintas(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _IFACE, "allowed_vlans": [10], "allowed_vlan_operation": "add"},
        {"interface": "GigabitEthernet0/0/24", "allowed_vlans": [20], "allowed_vlan_operation": "add"},
    ]})
    assert res.status_code == 202


def test_batch_202_una_entrada_de_allowed_vlans_mas_otros_campos_de_la_misma_interfaz(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _IFACE, "allowed_vlans": [10], "allowed_vlan_operation": "add"},
        {"interface": _IFACE, "description": "uplink"},
    ]})
    assert res.status_code == 202


def test_shutdown_501_unsupported_vendor(admin_client, monkeypatch):
    monkeypatch.setitem(plugin_registry._vendors, "juniper", StubUnimplementedDriver())
    fake_dev = Device(
        name="juniper-wr", host="192.0.2.99", vendor="juniper",
        username="admin", encrypted_password="enc", platform="junos",
    )
    monkeypatch.setattr(device_repository, "get", lambda name: fake_dev if name == "juniper-wr" else None)

    res = admin_client.post(_u("shutdown", "juniper-wr"), json={"interface": _IFACE})
    assert res.status_code == 501
    assert res.json()["error_code"] == "VENDOR_NOT_SUPPORTED"


def test_enable_501_unsupported_vendor(admin_client, monkeypatch):
    monkeypatch.setitem(plugin_registry._vendors, "juniper2", StubUnimplementedDriver())
    fake_dev = Device(
        name="juniper-wr2", host="192.0.2.99", vendor="juniper2",
        username="admin", encrypted_password="enc", platform="junos",
    )
    monkeypatch.setattr(device_repository, "get", lambda name: fake_dev if name == "juniper-wr2" else None)

    res = admin_client.post(_u("enable", "juniper-wr2"), json={"interface": _IFACE})
    assert res.status_code == 501


def test_shutdown_response_shape(operator_client, device):
    res = operator_client.post(_u("shutdown"), json={"interface": _IFACE})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["success"] is True
    assert "group_job_id" in body["data"]
    assert len(body["data"]["jobs"]) == 1
    assert body["data"]["jobs"][0]["device"] == _DEVICE


def test_enable_response_shape(operator_client, device):
    res = operator_client.post(_u("enable"), json={"interface": _IFACE})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["success"] is True
    assert "group_job_id" in body["data"]
    assert len(body["data"]["jobs"]) == 1


def test_admin_allowed(admin_client, device):
    res = admin_client.post(_u("shutdown"), json={"interface": _IFACE})
    assert res.status_code == 202, res.text


def test_shutdown_job_reaches_completed(operator_client, device):
    res = operator_client.post(_u("shutdown"), json={"interface": _IFACE})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"


def test_enable_job_reaches_completed(operator_client, device, fake_driver):
    res = operator_client.post(_u("enable"), json={"interface": _IFACE})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert job.result.get("noop") is True


def test_batch_multiple_fields_one_interface(operator_client, device, fake_driver):
    res = operator_client.post(
        _u("batch"),
        json={"changes": [{"interface": _IFACE, "description": "multi", "admin_up": False}]},
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    assert len(res.json()["data"]["jobs"]) == 1
    job = job_repository.get(job_id)
    assert job.status == "completed"
    ops = [op for op, _v, _vars in fake_driver.calls]
    assert "update_port_description" in ops
    assert "set_port_admin_state" in ops


def test_access_mode_with_vlan(operator_client, device, fake_driver):
    res = operator_client.post(_u("access-mode"), json={"interface": _IFACE, "access_vlan": 20})
    assert res.status_code == 202, res.text
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert any(op == "set_access_mode" for op, _v, _vars in fake_driver.calls)


def test_trunk_mode_with_vlans(operator_client, device, fake_driver):
    res = operator_client.post(
        _u("trunk-mode"), json={"interface": _IFACE, "native_vlan": 1, "allowed_vlans": [10, 20, 30]},
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert any(op == "set_trunk_mode" for op, _v, _vars in fake_driver.calls)


_TRUNK_IFACE = "GigabitEthernet0/0/24"


def test_trunk_mode_sobre_un_trunk_existente_manda_solo_el_delta(operator_client, device, fake_driver):
    res = operator_client.post(
        _u("trunk-mode"), json={"interface": _TRUNK_IFACE, "native_vlan": 1, "allowed_vlans": [10, 20, 30, 40]},
    )
    assert res.status_code == 202, res.text
    job = job_repository.get(res.json()["data"]["jobs"][0]["job_id"])
    assert job.status == "completed"
    assert not any(op == "set_trunk_mode" for op, _v, _vars in fake_driver.calls)
    assert [(op, v["pvid"], v["add"], v["remove"]) for op, _va, v in fake_driver.calls
            if op == "set_trunk_config_delta"] == [("set_trunk_config_delta", None, [40], [])]


def test_trunk_mode_identico_al_estado_actual_es_noop(operator_client, device, fake_driver):
    res = operator_client.post(
        _u("trunk-mode"), json={"interface": _TRUNK_IFACE, "native_vlan": 1, "allowed_vlans": [10, 20, 30]},
    )
    assert res.status_code == 202, res.text
    job = job_repository.get(res.json()["data"]["jobs"][0]["job_id"])
    assert job.status == "completed"
    assert job.result.get("noop") is True
    assert not any(op in ("set_trunk_mode", "set_trunk_config_delta") for op, _v, _vars in fake_driver.calls)


def test_trunk_mode_sobre_un_trunk_cambia_el_pvid_y_quita_vlans(operator_client, device, fake_driver):
    res = operator_client.post(
        _u("trunk-mode"), json={"interface": _TRUNK_IFACE, "native_vlan": 20, "allowed_vlans": [20, 30]},
    )
    assert res.status_code == 202, res.text
    assert [(v["pvid"], v["add"], v["remove"]) for op, _va, v in fake_driver.calls
            if op == "set_trunk_config_delta"] == [(20, [], [10])]


def test_batch_trunk_mode_sobre_un_trunk_manda_el_delta(operator_client, device, fake_driver):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _TRUNK_IFACE, "mode": "trunk", "access_vlan": 1, "allowed_vlans": [10, 20, 30, 50]},
    ]})
    assert res.status_code == 202, res.text
    assert [(v["pvid"], v["add"], v["remove"]) for op, _va, v in fake_driver.calls
            if op == "set_trunk_config_delta"] == [(None, [50], [])]
    assert not any(op == "set_trunk_mode" for op, _v, _vars in fake_driver.calls)


def test_batch_422_mode_trunk_mas_access_vlan_de_la_misma_interfaz(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _TRUNK_IFACE, "mode": "trunk", "access_vlan": 1, "allowed_vlans": [10, 20]},
        {"interface": _TRUNK_IFACE, "access_vlan": 5},
    ]})
    assert res.status_code == 422
    assert "single entry" in res.json()["message"]


def test_batch_202_access_vlan_y_allowed_vlans_sueltos_en_una_misma_entrada(operator_client, device):
    res = operator_client.post(_u("batch"), json={"changes": [
        {"interface": _TRUNK_IFACE, "access_vlan": 5, "allowed_vlans": [10], "allowed_vlan_operation": "add"},
    ]})
    assert res.status_code == 202
