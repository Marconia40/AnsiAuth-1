from app.composition import (
    device_repository,
    device_sync_service,
    inventory,
    plugin_registry,
    site_repository,
)
from app.core.exceptions import ValidationError as _ValidationError
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


_ensure_device("mock_device")
_ensure_device("fail_device")


def test_create_vlan_success(client):
    payload = {"vlan_id": 800, "name": "TEST", "devices": ["mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 1
    assert "job_id" in data["jobs"][0]
    assert data["jobs"][0]["status"] in ("pending", "running", "completed")


def test_vlan_invalid_id(client):
    payload = {"vlan_id": 5000, "name": "TEST", "devices": ["mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 422
    assert response.json()["details"]["errors"][0]["type"] == "less_than_equal"


def test_vlan_reserved(client):
    payload = {"vlan_id": 1, "name": "TEST", "devices": ["mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 422
    assert "reserved" in response.text


def test_vlan_name_invalid(client):
    payload = {"vlan_id": 20, "name": "INVALID NAME", "devices": ["mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 422


def test_get_vlans(client):
    response = client.get("/api/v1/vlans/?device=mock_device")
    assert response.status_code == 200
    envelope = response.json()["data"]
    vlans = envelope["data"]
    assert isinstance(vlans, list)
    assert len(vlans) > 0
    assert "vlan_id" in vlans[0]
    assert "name" in vlans[0]


def test_delete_vlan_success(client):
    response = client.request("DELETE", "/api/v1/vlans/10", json={"devices": ["mock_device"]})
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 1
    job = data["jobs"][0]
    assert "job_id" in job
    assert job["device"] == "mock_device"


def test_delete_vlan_invalid(client):
    response = client.request("DELETE", "/api/v1/vlans/1", json={"devices": ["mock_device"]})
    assert response.status_code == 422
    assert "reserved" in response.text


def test_update_vlan_reserved_id(client):
    payload = {"description": "Should be blocked", "devices": ["mock_device"]}
    response = client.patch("/api/v1/vlans/1", json=payload)
    assert response.status_code == 422
    assert "reserved" in response.text


def test_update_vlan_reserved_id_range(client):
    payload = {"description": "Should be blocked", "devices": ["mock_device"]}
    response = client.patch("/api/v1/vlans/1002", json=payload)
    assert response.status_code == 422
    assert "reserved" in response.text


def test_update_vlan_description(client):
    payload = {"description": "Core-network-VLAN", "devices": ["mock_device"]}
    response = client.patch("/api/v1/vlans/10", json=payload)
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 1
    job = data["jobs"][0]
    assert "job_id" in job
    assert job["device"] == "mock_device"


def test_create_vlan_device_not_found(client):
    payload = {"vlan_id": 50, "name": "TEST", "devices": ["nonexistent_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 404
    assert "nonexistent_device" in response.text


def test_create_vlan_empty_devices_rejected(client):
    payload = {"vlan_id": 50, "name": "TEST", "devices": []}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 422


def test_delete_vlan_failure(client):
    response = client.request("DELETE", "/api/v1/vlans/10", json={"devices": ["fail_device"]})
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]
    response = client.get(f"/api/v1/jobs/{job_id}")
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["error"] is not None


def test_update_vlan_failure(client):
    payload = {"description": "Test-desc", "devices": ["fail_device"]}
    response = client.patch("/api/v1/vlans/10", json=payload)
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]
    response = client.get(f"/api/v1/jobs/{job_id}")
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["error"] is not None


def test_delete_nonexistent_vlan_job_completes_as_noop(client):
    response = client.request("DELETE", "/api/v1/vlans/99", json={"devices": ["mock_device"]})
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]
    response = client.get(f"/api/v1/jobs/{job_id}")
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["result"]["noop"] is True


def test_delete_multi_device(client):
    response = client.request("DELETE", "/api/v1/vlans/10", json={"devices": ["mock_device", "mock_device"]})
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 2
    for job in data["jobs"]:
        assert "job_id" in job
        assert job["device"] == "mock_device"


def test_update_multi_device(client):
    payload = {"description": "Multi-update", "devices": ["mock_device", "mock_device"]}
    response = client.patch("/api/v1/vlans/10", json=payload)
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 2
    for job in data["jobs"]:
        assert "job_id" in job
        assert job["device"] == "mock_device"


def test_delete_valid_vlan_still_works(client):
    response = client.request("DELETE", "/api/v1/vlans/10", json={"devices": ["mock_device"]})
    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["jobs"]) == 1


def test_get_vlans_no_device_real_mode_returns_400(client, monkeypatch):
    monkeypatch.setattr("app.core.config.EXECUTION_MODE", "real")
    response = client.get("/api/v1/vlans/")
    assert response.status_code == 422
    assert "device" in response.json()["message"].lower()


def test_get_vlans_no_device_mock_mode_returns_list(client, monkeypatch):
    monkeypatch.setattr("app.core.config.EXECUTION_MODE", "mock")
    response = client.get("/api/v1/vlans/")
    assert response.status_code == 200
    envelope = response.json()["data"]
    assert isinstance(envelope["data"], list)
    assert len(envelope["data"]) > 0


def test_get_vlans_with_device_returns_cached_data(client):
    response = client.get("/api/v1/vlans/?device=mock_device")
    assert response.status_code == 200
    envelope = response.json()["data"]
    assert isinstance(envelope["data"], list)
