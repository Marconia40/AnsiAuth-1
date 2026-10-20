from __future__ import annotations

import pytest

from app.composition import device_repository, job_repository, plugin_registry
from app.models.device import Device

from tests._puerto_fakes import FakePuertoDriver, StubUnimplementedDriver, get_or_create_device

_DEVICE = "adm_dev"
_IFACE = "GigabitEthernet0/0/1"


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakePuertoDriver()
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    return drv


@pytest.fixture
def device(fake_driver):
    return get_or_create_device(_DEVICE, site_name="Admin State Test Site")


def _url(name: str = _DEVICE) -> str:
    return f"/api/v1/devices/{name}/ports/admin-state"


def test_patch_rejects_unauthenticated(unauth_client, device):
    res = unauth_client.patch(_url(), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 401


def test_patch_rejects_observer(observer_client, device):
    res = observer_client.patch(_url(), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 403


def test_patch_operator_allowed(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["success"] is True
    assert "group_job_id" in body["data"]
    assert body["data"]["jobs"][0]["device"] == _DEVICE
    assert body["data"]["jobs"][0]["job_id"]


def test_patch_validates_interface_name(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": "", "enabled": False})
    assert res.status_code == 422


def test_patch_unknown_device_returns_404(operator_client, fake_driver):
    res = operator_client.patch(_url("no-such-device"), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 404


def test_patch_unsupported_vendor_returns_friendly_501(admin_client, monkeypatch):
    monkeypatch.setitem(plugin_registry._vendors, "juniper", StubUnimplementedDriver())
    fake_dev = Device(
        name="juniper-x2", host="192.0.2.99", vendor="juniper",
        username="admin", encrypted_password="enc", platform="junos",
    )
    monkeypatch.setattr(device_repository, "get", lambda name: fake_dev if name == "juniper-x2" else None)

    res = admin_client.patch(_url("juniper-x2"), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 501
    body = res.json()
    assert body["error_code"] == "VENDOR_NOT_SUPPORTED"
    blob = res.text.lower()
    assert "juniper" not in blob
    assert "junos" not in blob


def test_end_to_end_disable_completes_in_mock(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]

    job = job_repository.get(job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.retry_count == 0
    assert job.rollback_performed in (False, None)


def test_end_to_end_noop_when_already_in_state(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": _IFACE, "enabled": True})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert job.result.get("noop") is True
    assert not any(op == "set_port_admin_state" for op, _v, _vars in fake_driver.calls)


def test_end_to_end_failure_triggers_rollback(operator_client, device, fake_driver):
    def _fail_on(op_key, vars):
        return op_key == "set_port_admin_state" and vars.get("enabled") is False
    fake_driver.fail_on = _fail_on
    fake_driver.stateful = True
    fake_driver.mutate_before_fail = True

    res = operator_client.patch(_url(), json={"interface": _IFACE, "enabled": False})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]

    job = job_repository.get(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.rollback_performed is True
    assert job.rollback_success is True
    assert ("rollback:set_port_admin_state", None, {"interface": _IFACE, "enabled": True}) in fake_driver.calls


def test_end_to_end_unknown_interface_fails_cleanly(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": "GigabitEthernet9/9/9", "enabled": False})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
