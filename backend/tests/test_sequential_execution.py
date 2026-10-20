import threading

from app.composition import (
    device_repository,
    device_sync_service,
    inventory,
    plugin_registry,
    site_repository,
)
from app.core.exceptions import ValidationError as _ValidationError
from app.models.vlan import VLAN
from app.services.vendors.mock import MockVendor

plugin_registry.registrar("cisco_ios", MockVendor())
plugin_registry.registrar("huawei_vrp", MockVendor())

_SITE_NAME = "VLAN Orchestration Test Site"


def _ensure_site(name: str = _SITE_NAME):
    try:
        return site_repository.crear_con_grupo_default(name, kind="REGULAR")
    except ValueError:
        return site_repository.list(name=name)[0]


def _ensure_device(name: str, vendor: str = "cisco_ios", host: "str | None" = None):
    existing = device_repository.get(name)
    if existing is not None:
        return existing
    site = _ensure_site()
    try:
        device = inventory.register(
            name=name, host=host or f"10.90.0.{abs(hash(name)) % 250 + 1}",
            vendor=vendor, platform="ios",
            username="admin", password="admin123",
            site_id=site.id, device_group_id=None,
            actor={"username": "test-setup"},
        )
    except _ValidationError:
        return device_repository.get(name)
    try:
        device_sync_service.sync_vlans(device)
    except Exception:
        pass
    return device


def _seed_devices(*specs):
    for name, host in specs:
        _ensure_device(name, host=host)


_ensure_device("mock_device")
_ensure_device("fail_device")


def test_create_failure_isolation_middle_device(client, monkeypatch):
    _seed_devices(("sq_c1", "10.50.1.1"), ("sq_c3", "10.50.1.3"))

    executed: list[str] = []

    def selective_create(self, vlan_id, name, device, password):
        executed.append(device.name)
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", selective_create)

    payload = {"vlan_id": 501, "name": "SEQTEST", "devices": ["sq_c1", "fail_device", "sq_c3"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202
    group_job_id = resp.json()["data"]["group_job_id"]
    assert len(resp.json()["data"]["jobs"]) == 3

    assert executed == ["sq_c1", "fail_device", "sq_c3"]

    gj = client.get(f"/api/v1/group-jobs/{group_job_id}").json()["data"]
    assert gj["status"] == "partial_success"
    s = gj["execution_summary"]
    assert s["total_devices"] == 3
    assert s["completed"] == 2
    assert s["failed"] == 1


def test_create_failure_isolation_first_device(client, monkeypatch):
    _seed_devices(("sq_c4", "10.50.2.1"), ("sq_c5", "10.50.2.2"))

    executed: list[str] = []

    def selective_create(self, vlan_id, name, device, password):
        executed.append(device.name)
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", selective_create)

    payload = {"vlan_id": 502, "name": "SEQFIRST", "devices": ["fail_device", "sq_c4", "sq_c5"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202
    group_job_id = resp.json()["data"]["group_job_id"]

    assert executed == ["fail_device", "sq_c4", "sq_c5"]

    gj = client.get(f"/api/v1/group-jobs/{group_job_id}").json()["data"]
    assert gj["status"] == "partial_success"
    assert gj["execution_summary"]["completed"] == 2
    assert gj["execution_summary"]["failed"] == 1


def test_create_failure_isolation_last_device(client, monkeypatch):
    _seed_devices(("sq_c6", "10.50.3.1"), ("sq_c7", "10.50.3.2"))

    executed: list[str] = []

    def selective_create(self, vlan_id, name, device, password):
        executed.append(device.name)
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", selective_create)

    payload = {"vlan_id": 503, "name": "SEQLAST", "devices": ["sq_c6", "sq_c7", "fail_device"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202

    assert executed == ["sq_c6", "sq_c7", "fail_device"]

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["status"] == "partial_success"


def test_create_all_devices_succeed(client, monkeypatch):
    _seed_devices(("sq_ok1", "10.50.4.1"), ("sq_ok2", "10.50.4.2"))

    executed: list[str] = []

    def track_create(self, vlan_id, name, device, password):
        executed.append(device.name)
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", track_create)

    payload = {"vlan_id": 504, "name": "ALLOK", "devices": ["sq_ok1", "sq_ok2"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202

    assert executed == ["sq_ok1", "sq_ok2"]

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["status"] == "completed"
    assert gj["execution_summary"]["completed"] == 2
    assert gj["execution_summary"]["failed"] == 0


def test_create_all_devices_fail(client, monkeypatch):
    _seed_devices(("sq_f1", "10.50.5.1"), ("sq_f2", "10.50.5.2"))

    executed: list[str] = []

    def all_fail(self, vlan_id, name, device, password):
        executed.append(device.name)
        return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}

    monkeypatch.setattr(MockVendor, "create_vlan", all_fail)

    payload = {"vlan_id": 505, "name": "ALLFAIL", "devices": ["sq_f1", "sq_f2"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202

    assert executed == ["sq_f1", "sq_f2"]

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["status"] == "failed"
    assert gj["execution_summary"]["failed"] == 2
    assert gj["execution_summary"]["completed"] == 0


def test_sequential_ordering_three_devices(client, monkeypatch):
    _seed_devices(("ord_a", "10.50.6.1"), ("ord_b", "10.50.6.2"), ("ord_c", "10.50.6.3"))

    execution_order: list[str] = []
    active: list[str] = []
    max_concurrent = [0]
    lock = threading.Lock()

    def tracked_create(self, vlan_id, name, device, password):
        with lock:
            active.append(device.name)
            max_concurrent[0] = max(max_concurrent[0], len(active))
        result = {"rc": 0, "stdout": "ok", "stderr": ""}
        with lock:
            execution_order.append(device.name)
            active.remove(device.name)
        return result

    monkeypatch.setattr(MockVendor, "create_vlan", tracked_create)

    payload = {"vlan_id": 506, "name": "ORDTEST", "devices": ["ord_a", "ord_b", "ord_c"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202

    assert execution_order == ["ord_a", "ord_b", "ord_c"]
    assert max_concurrent[0] == 1


def test_sequential_ordering_two_devices_with_failure(client, monkeypatch):
    _seed_devices(("ord_d", "10.50.7.1"))

    execution_order: list[str] = []

    def selective(self, vlan_id, name, device, password):
        execution_order.append(device.name)
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", selective)

    payload = {"vlan_id": 507, "name": "ORDWFAIL", "devices": ["fail_device", "ord_d"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202

    assert execution_order == ["fail_device", "ord_d"]


def test_update_failure_isolation(client):
    _seed_devices(("upd_a", "10.50.8.1"), ("upd_b", "10.50.8.2"))

    payload = {"description": "NewDesc", "devices": ["upd_a", "fail_device", "upd_b"]}
    resp = client.patch("/api/v1/vlans/10", json=payload)
    assert resp.status_code == 202

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["status"] == "partial_success"
    assert gj["execution_summary"]["total_devices"] == 3
    assert gj["execution_summary"]["completed"] == 2
    assert gj["execution_summary"]["failed"] == 1

    devices_attempted = {r["device"] for r in gj["device_results"]}
    assert devices_attempted == {"upd_a", "fail_device", "upd_b"}


def test_update_all_succeed(client):
    _seed_devices(("upd_c", "10.50.9.1"), ("upd_d", "10.50.9.2"))

    resp = client.patch("/api/v1/vlans/10", json={"description": "OK", "devices": ["upd_c", "upd_d"]})
    assert resp.status_code == 202

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["status"] == "completed"
    assert gj["execution_summary"]["completed"] == 2


def test_delete_failure_isolation(client, monkeypatch):
    _seed_devices(("del_a", "10.50.10.1"), ("del_b", "10.50.10.2"))

    monkeypatch.setattr(
        MockVendor, "get_vlans",
        lambda self, device, password: [VLAN(vlan_id=555, name="DELTEST")],
    )

    executed_delete: list[str] = []

    def selective_delete(self, vlan_id, device, password):
        executed_delete.append(device.name)
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "delete_vlan", selective_delete)

    resp = client.request("DELETE", "/api/v1/vlans/555", json={"devices": ["del_a", "fail_device", "del_b"]})
    assert resp.status_code == 202

    assert executed_delete == ["del_a", "fail_device", "del_b"]

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["execution_summary"]["total_devices"] == 3
    assert gj["execution_summary"]["failed"] >= 1
    devices_attempted = {r["device"] for r in gj["device_results"]}
    assert devices_attempted == {"del_a", "fail_device", "del_b"}


def test_delete_all_succeed(client, monkeypatch):
    _seed_devices(("del_c", "10.50.11.1"), ("del_d", "10.50.11.2"))

    monkeypatch.setattr(
        MockVendor, "get_vlans",
        lambda self, device, password: [VLAN(vlan_id=556, name="DTEST")],
    )
    monkeypatch.setattr(
        MockVendor, "delete_vlan",
        lambda self, vlan_id, device, password: {"rc": 0, "stdout": "ok", "stderr": ""},
    )

    resp = client.request("DELETE", "/api/v1/vlans/556", json={"devices": ["del_c", "del_d"]})
    assert resp.status_code == 202

    gj = client.get(f"/api/v1/group-jobs/{resp.json()['data']['group_job_id']}").json()["data"]
    assert gj["execution_summary"]["total_devices"] == 2
    assert gj["status"] == "completed"


def test_device_results_reflect_individual_outcomes(client, monkeypatch):
    _seed_devices(("dr_a", "10.50.12.1"), ("dr_b", "10.50.12.2"))

    def selective(self, vlan_id, name, device, password):
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "err"}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", selective)

    payload = {"vlan_id": 508, "name": "DRTEST", "devices": ["dr_a", "fail_device", "dr_b"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    group_job_id = resp.json()["data"]["group_job_id"]

    gj = client.get(f"/api/v1/group-jobs/{group_job_id}").json()["data"]
    results_by_device = {r["device"]: r for r in gj["device_results"]}

    assert results_by_device["dr_a"]["status"] == "completed"
    assert results_by_device["fail_device"]["status"] == "failed"
    assert results_by_device["dr_b"]["status"] == "completed"

    assert results_by_device["dr_a"]["job_id"] is not None
    assert results_by_device["fail_device"]["job_id"] is not None


def test_single_device_create_still_works(client, monkeypatch):
    executed: list[str] = []

    def track(self, vlan_id, name, device, password):
        executed.append(device.name)
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", track)

    resp = client.post("/api/v1/vlans/", json={"vlan_id": 509, "name": "COMPAT", "devices": ["mock_device"]})
    assert resp.status_code == 202
    data = resp.json()["data"]

    assert len(data["jobs"]) == 1
    assert "group_job_id" in data
    assert executed == ["mock_device"]

    gj = client.get(f"/api/v1/group-jobs/{data['group_job_id']}").json()["data"]
    assert gj["status"] == "completed"
    assert gj["execution_summary"]["total_devices"] == 1


def test_single_device_update_still_works(client, monkeypatch):
    executed: list[str] = []

    def track_update(self, vlan_id, name, device, password):
        executed.append(device.name)
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "update_vlan", track_update)

    resp = client.patch("/api/v1/vlans/10", json={"description": "Solo", "devices": ["mock_device"]})
    assert resp.status_code == 202
    data = resp.json()["data"]

    assert "group_job_id" in data
    assert executed == ["mock_device"]
