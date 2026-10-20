from __future__ import annotations

import pytest

from app.composition import device_repository, job_repository, plugin_registry
from app.models.device import Device
from app.models.port import Puerto
from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor

from tests._puerto_fakes import FakePuertoDriver, StubUnimplementedDriver, get_or_create_device

_DEVICE = "trunk_dev"
_IFACE_TRUNK = "GigabitEthernet0/0/24"
_IFACE_ACCESS = "GigabitEthernet0/0/1"


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakePuertoDriver()
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    return drv


@pytest.fixture
def device(fake_driver):
    return get_or_create_device(_DEVICE, site_name="Trunk VLANs Test Site")


def _url(name: str = _DEVICE) -> str:
    return f"/api/v1/devices/{name}/ports/trunk-vlans"


_TRUNK_OPS = ("set_trunk_vlans_delta", "set_trunk_allowed_vlans")


def _trunk_calls(fake_driver):
    return [(op, v) for op, _va, v in fake_driver.calls if op in _TRUNK_OPS]


def test_compress_vlans_cisco_single():
    assert CiscoVendor()._compress_vlans_cisco([10]) == "10"


def test_compress_vlans_cisco_range():
    assert CiscoVendor()._compress_vlans_cisco([10, 11, 12]) == "10-12"


def test_compress_vlans_cisco_mixed():
    assert CiscoVendor()._compress_vlans_cisco([10, 11, 12, 20, 30, 31]) == "10-12,20,30-31"


def test_compress_vlans_cisco_unordered_dedup():
    assert CiscoVendor()._compress_vlans_cisco(sorted(set([30, 10, 11, 30, 12]))) == "10-12,30"


def test_compress_vlans_huawei_single():
    assert HuaweiVendor()._compress_vlans_huawei([10]) == "10"


def test_compress_vlans_huawei_range():
    assert HuaweiVendor()._compress_vlans_huawei([10, 11, 12]) == "10 to 12"


def test_compress_vlans_huawei_mixed():
    assert HuaweiVendor()._compress_vlans_huawei([10, 11, 12, 20, 30, 31]) == "10 to 12 20 30 to 31"


class _FakeVlanDriver:
    def resolver_set_trunk_allowed_vlans(self, interface, vlan_list):
        return ("set_trunk_allowed_vlans", None, {"interface": interface, "vlan_list": list(vlan_list)})

    def resolver_set_trunk_vlans_delta(self, interface, add, remove):
        return ("set_trunk_vlans_delta", None, {"interface": interface, "add": list(add), "remove": list(remove)})


class _FakeVlanDevice:
    driver = _FakeVlanDriver()


def _paso(operation: str, current: "list[int] | None", requested: list[int]):
    actual = None if current is None else Puerto(interface="Gi0/1", mode="trunk", allowed_vlans=current)
    p = Puerto(interface="Gi0/1", allowed_vlans=requested, allowed_vlan_operation=operation)
    return p._resolver_allowed_vlans(_FakeVlanDevice(), actual)


def _delta(operation: str, current: "list[int] | None", requested: list[int]) -> "tuple[list[int], list[int]]":
    paso = _paso(operation, current, requested)
    assert paso is not None
    op_key, _variant, vars = paso
    assert op_key == "set_trunk_vlans_delta"
    return vars["add"], vars["remove"]


def _desired(operation: str, current: "list[int] | None", requested: list[int]) -> list[int]:
    paso = _paso(operation, current, requested)
    assert paso is not None
    op_key, _variant, vars = paso
    if op_key == "set_trunk_allowed_vlans":
        return vars["vlan_list"]
    return sorted((set(current or []) | set(vars["add"])) - set(vars["remove"]))


def test_compute_replace():
    assert _desired("replace", [1, 10], [20, 30]) == [20, 30]


def test_compute_replace_no_current_needed():
    assert _desired("replace", None, [10, 20]) == [10, 20]


def test_compute_add():
    assert _desired("add", [1, 10], [10, 20]) == [1, 10, 20]


def test_compute_add_raises_when_current_unknown():
    p = Puerto(interface="Gi0/1", allowed_vlans=[10], allowed_vlan_operation="add")
    with pytest.raises(ValueError):
        p._resolver_allowed_vlans(_FakeVlanDevice(), None)


def test_compute_remove():
    assert _desired("remove", [1, 10, 20], [10]) == [1, 20]


def test_compute_remove_raises_when_current_unknown():
    p = Puerto(interface="Gi0/1", allowed_vlans=[10], allowed_vlan_operation="remove")
    with pytest.raises(ValueError):
        p._resolver_allowed_vlans(_FakeVlanDevice(), None)


def test_compute_remove_to_empty_raises():
    actual = Puerto(interface="Gi0/1", mode="trunk", allowed_vlans=[10])
    p = Puerto(interface="Gi0/1", allowed_vlans=[10], allowed_vlan_operation="remove")
    with pytest.raises(ValueError):
        p._resolver_allowed_vlans(_FakeVlanDevice(), actual)


def test_delta_add_manda_solo_lo_que_falta():
    assert _delta("add", [1, 10], [10, 20]) == ([20], [])


def test_delta_remove_manda_solo_lo_que_sobra():
    assert _delta("remove", [1, 10, 20], [10]) == ([], [10])


def test_delta_remove_no_emite_undo_de_una_vlan_que_no_esta():
    assert _delta("remove", [1, 10, 20], [10, 99]) == ([], [10])


def test_delta_add_no_reenvia_una_vlan_que_ya_esta():
    assert _delta("add", [1, 10], [10, 20, 30]) == ([20, 30], [])


def test_delta_replace_con_estado_conocido_agrega_y_quita_sin_undo_all():
    assert _delta("replace", [10, 20, 30], [30, 40, 50]) == ([40, 50], [10, 20])


def test_delta_replace_sin_estado_conserva_el_reemplazo_completo():
    op_key, _variant, vars = _paso("replace", None, [10, 20])
    assert op_key == "set_trunk_allowed_vlans"
    assert vars["vlan_list"] == [10, 20]


@pytest.mark.parametrize("operation,requested", [("add", [10, 20]), ("remove", [99]), ("replace", [1, 10, 20])])
def test_delta_vacio_es_noop(operation, requested):
    assert _paso(operation, [1, 10, 20], requested) is None


def test_patch_rejects_unauthenticated(unauth_client, device):
    res = unauth_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [40, 50]})
    assert res.status_code == 401


def test_patch_rejects_observer(observer_client, device):
    res = observer_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [40, 50]})
    assert res.status_code == 403


def test_patch_operator_allowed(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [40, 50]})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["success"] is True
    assert "group_job_id" in body["data"]
    assert body["data"]["jobs"][0]["device"] == _DEVICE
    assert body["data"]["jobs"][0]["job_id"]


def test_patch_unknown_device_returns_404(operator_client, fake_driver):
    res = operator_client.patch(_url("no-such-device"), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [10]})
    assert res.status_code == 404


def test_patch_unsupported_vendor_returns_friendly_501(admin_client, monkeypatch):
    monkeypatch.setitem(plugin_registry._vendors, "juniper", StubUnimplementedDriver())
    fake_dev = Device(
        name="juniper-x4", host="192.0.2.99", vendor="juniper",
        username="admin", encrypted_password="enc", platform="junos",
    )
    monkeypatch.setattr(device_repository, "get", lambda name: fake_dev if name == "juniper-x4" else None)

    res = admin_client.patch(_url("juniper-x4"), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [10]})
    assert res.status_code == 501
    body = res.json()
    assert body["error_code"] == "VENDOR_NOT_SUPPORTED"
    blob = res.text.lower()
    assert "juniper" not in blob
    assert "junos" not in blob


@pytest.mark.parametrize("vlan_id", [1002, 1003, 1004, 1005])
def test_reserved_vlan_ids_rejected(operator_client, device, vlan_id):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [vlan_id]})
    assert res.status_code == 422


def test_vlan_id_out_of_range_rejected(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [4095]})
    assert res.status_code == 422


def test_empty_vlans_list_rejected(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": []})
    assert res.status_code == 422


def test_duplicate_vlans_accepted_and_deduplicated(operator_client, device):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [40, 40]})
    assert res.status_code == 202


def test_e2e_replace_completes(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [40, 50]})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.retry_count == 0
    assert job.rollback_performed in (False, None)
    assert _trunk_calls(fake_driver) == [
        ("set_trunk_vlans_delta", {"interface": _IFACE_TRUNK, "add": [40, 50], "remove": [10, 20, 30]}),
    ]


def test_e2e_add_merges_with_current(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "add", "vlans": [40]})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert _trunk_calls(fake_driver) == [
        ("set_trunk_vlans_delta", {"interface": _IFACE_TRUNK, "add": [40], "remove": []}),
    ]


def test_e2e_remove_subtracts_from_current(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "remove", "vlans": [20]})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert _trunk_calls(fake_driver) == [
        ("set_trunk_vlans_delta", {"interface": _IFACE_TRUNK, "add": [], "remove": [20]}),
    ]


def test_e2e_noop_when_replace_already_matches(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [10, 20, 30]})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
    assert job.result.get("noop") is True
    assert not _trunk_calls(fake_driver)


def test_e2e_access_port_fails_cleanly(operator_client, device, fake_driver):
    res = operator_client.patch(_url(), json={"interface": _IFACE_ACCESS, "mode": "replace", "vlans": [10]})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "failed"
    assert "trunk" in (job.error or "").lower()
    assert not _trunk_calls(fake_driver)


def test_e2e_add_fails_when_current_vlans_unknown(operator_client, fake_driver):
    unknown_trunk = Puerto(interface="GigabitEthernet0/0/30", mode="trunk", access_vlan=1, allowed_vlans=None)
    fake_driver.ports.append(unknown_trunk)
    dev = get_or_create_device("trunk_dev_unknown", site_name="Trunk VLANs Test Site")

    res = operator_client.patch(
        f"/api/v1/devices/{dev.name}/ports/trunk-vlans",
        json={"interface": "GigabitEthernet0/0/30", "mode": "add", "vlans": [10]},
    )
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "failed"
    assert not _trunk_calls(fake_driver)


def test_e2e_replace_succeeds_when_current_vlans_unknown(operator_client, fake_driver):
    unknown_trunk = Puerto(interface="GigabitEthernet0/0/31", mode="trunk", access_vlan=1, allowed_vlans=None)
    fake_driver.ports.append(unknown_trunk)
    dev = get_or_create_device("trunk_dev_unknown2", site_name="Trunk VLANs Test Site")

    res = operator_client.patch(
        f"/api/v1/devices/{dev.name}/ports/trunk-vlans",
        json={"interface": "GigabitEthernet0/0/31", "mode": "replace", "vlans": [10, 20]},
    )
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"


def test_e2e_remove_would_empty_trunk_rejected(operator_client, fake_driver):
    single_vlan_trunk = Puerto(interface="GigabitEthernet0/0/32", mode="trunk", access_vlan=1, allowed_vlans=[10])
    fake_driver.ports.append(single_vlan_trunk)
    dev = get_or_create_device("trunk_dev_single", site_name="Trunk VLANs Test Site")

    res = operator_client.patch(
        f"/api/v1/devices/{dev.name}/ports/trunk-vlans",
        json={"interface": "GigabitEthernet0/0/32", "mode": "remove", "vlans": [10]},
    )
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "failed"
    assert "permitidas" in (job.error or "").lower() or "empty" in (job.error or "").lower()
    assert not _trunk_calls(fake_driver)


def test_e2e_failure_triggers_rollback(operator_client, device, fake_driver):
    fake_driver.stateful = True
    fake_driver.mutate_before_fail = True
    fake_driver.fail_on = lambda op_key, vars: op_key == "set_trunk_vlans_delta" and vars.get("add") == [40, 50]

    res = operator_client.patch(_url(), json={"interface": _IFACE_TRUNK, "mode": "replace", "vlans": [40, 50]})
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]

    job = job_repository.get(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.rollback_performed is True
    assert job.rollback_success is True
    assert (
        "set_trunk_vlans_delta", "both",
        {"interface": _IFACE_TRUNK, "add": [10, 20, 30], "remove": [40, 50]},
    ) in fake_driver.calls
    assert not any(
        op in ("set_trunk_allowed_vlans", "rollback:set_trunk_allowed_vlans")
        for op, _v, _vars in fake_driver.calls
    )
    trunk = next(p for p in fake_driver.ports if p.interface == _IFACE_TRUNK)
    assert trunk.allowed_vlans == [10, 20, 30]


def test_e2e_unknown_interface_completes(operator_client, device, fake_driver):
    res = operator_client.patch(
        _url(), json={"interface": "GigabitEthernet9/9/9", "mode": "replace", "vlans": [10]},
    )
    assert res.status_code == 202
    job_id = res.json()["data"]["jobs"][0]["job_id"]
    job = job_repository.get(job_id)
    assert job.status == "completed"
