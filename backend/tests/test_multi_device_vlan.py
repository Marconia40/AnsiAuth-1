import time

from app.composition import (
    audit_repository,
    device_repository,
    device_sync_service,
    inventory,
    plugin_registry,
    site_repository,
)
from app.core.exceptions import ValidationError as _ValidationError
from app.models.visibility_scope import VisibilityScope
from app.services.vendors.mock import MockVendor

plugin_registry.registrar("cisco_ios", MockVendor())
plugin_registry.registrar("huawei_vrp", MockVendor())

_SITE_NAME = "VLAN Orchestration Test Site"
_ADMIN_SCOPE = VisibilityScope(es_system_admin=True, grants=())


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


_ensure_device("mock_device")
_ensure_device("fail_device")


def test_multi_device_creates_multiple_audit_rows(client, admin_client):
    payload = {"vlan_id": 200, "name": "AUDITCHECK", "devices": ["mock_device", "mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202

    records, _total = audit_repository.query(
        scope=_ADMIN_SCOPE, device_id="mock_device", page=1, page_size=20,
    )
    entries = [e for e in records if e.action == "crear_vlan" and "VLAN 200" in (e.summary or "")]
    assert len(entries) == 2
    for entry in entries:
        assert entry.device == "mock_device"
        assert entry.status == "success"


def test_multi_device_inventory_matching(admin_client):
    for name, host in [("cisco1", "10.10.10.1"), ("cisco2", "10.10.10.2")]:
        _ensure_device(name, host=host)

    payload = {"vlan_id": 110, "name": "INVTEST", "devices": ["cisco1", "cisco2"]}
    response = admin_client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    jobs = response.json()["data"]["jobs"]
    assert len(jobs) == 2
    assert {j["device"] for j in jobs} == {"cisco1", "cisco2"}

    for j in jobs:
        job = admin_client.get(f"/api/v1/jobs/{j['job_id']}").json()["data"]
        assert job["status"] == "completed"
        assert job["device"] in {"cisco1", "cisco2"}


def test_multi_device_vlan(client):
    payload = {"vlan_id": 100, "name": "MULTI_TEST", "devices": ["mock_device", "mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 2
    for entry in data["jobs"]:
        assert "device" in entry
        assert "job_id" in entry
        assert "status" in entry
        assert entry["device"] == "mock_device"


def test_one_device_fails(client):
    payload = {
        "vlan_id": 101,
        "name": "ONETESTFAIL",
        "devices": ["mock_device", "fail_device"],
    }
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    data = response.json()["data"]
    jobs = {entry["device"]: entry["job_id"] for entry in data["jobs"]}

    resp = client.get(f"/api/v1/jobs/{jobs['mock_device']}")
    assert resp.json()["data"]["status"] == "completed"

    resp = client.get(f"/api/v1/jobs/{jobs['fail_device']}")
    result = resp.json()["data"]
    assert result["status"] == "failed"
    assert result["error"] is not None


def test_all_devices_success(client):
    payload = {
        "vlan_id": 102,
        "name": "ALLSUCCESS",
        "devices": ["mock_device", "mock_device"],
    }
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    data = response.json()["data"]

    for entry in data["jobs"]:
        resp = client.get(f"/api/v1/jobs/{entry['job_id']}")
        assert resp.json()["data"]["status"] == "completed"


def test_multi_device_unknown_device(client):
    payload = {
        "vlan_id": 103,
        "name": "BADDEV",
        "devices": ["mock_device", "no_such_device"],
    }
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 404
    assert "no_such_device" in response.text


def test_empty_devices_rejected(client):
    payload = {"vlan_id": 105, "name": "NODEV", "devices": []}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 422


def test_missing_devices_field_rejected(client):
    payload = {"vlan_id": 106, "name": "NOFIELD"}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 422
