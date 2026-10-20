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
from app.models.vlan import VLAN
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


def _latest_audit_entry(device: str = "mock_device", vlan_id: "int | None" = None):
    records, _total = audit_repository.query(
        scope=_ADMIN_SCOPE, device_id=device, page=1, page_size=20,
    )
    if vlan_id is not None:
        records = [r for r in records if f"VLAN {vlan_id}" in (r.summary or "")]
    return records[0]


def test_create_existing_vlan_same_name_noop(operator_client, client, monkeypatch):
    monkeypatch.setattr(
        MockVendor, "get_vlans",
        lambda self, device, password: [VLAN(vlan_id=50, name="MGMT50")],
    )

    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 50, "name": "MGMT50", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"
    assert job["result"]["noop"] is True

    entry = _latest_audit_entry(vlan_id=50)
    assert entry.status == "success"
    assert "no changes needed" in (entry.summary or "")


def test_create_new_vlan_succeeds(operator_client, client):
    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 800, "name": "NEW", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"


def test_update_existing_vlan_succeeds(operator_client, client):
    response = operator_client.patch(
        "/api/v1/vlans/10", json={"description": "Updated-name", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"
