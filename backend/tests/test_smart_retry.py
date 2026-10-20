import app.services.orquestador as orquestador_module
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


def _dejar_vlan_creada(vlan_id, name):
    from app.models.vlan import VLAN
    from app.services.vendors.mock import _mock_vlans

    if not any(v.vlan_id == vlan_id for v in _mock_vlans):
        _mock_vlans.append(VLAN(vlan_id=vlan_id, name=name))


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


def test_ssh_failure_retries_and_fails(operator_client, client, monkeypatch, restore_mock_vlans):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda s: None)

    call_count = {"n": 0}
    delete_count = {"n": 0}

    def _ssh_failure(self, vlan_id, name, device, password):
        call_count["n"] += 1
        if call_count["n"] == 4:
            _dejar_vlan_creada(vlan_id, name)
        return {"rc": 1, "stdout": "", "stderr": "SSH connection refused to host"}

    def _delete_also_fails(self, vlan_id, device, password):
        delete_count["n"] += 1
        return {"rc": 1, "stdout": "", "stderr": "SSH connection refused to host"}

    monkeypatch.setattr(MockVendor, "create_vlan", _ssh_failure)
    monkeypatch.setattr(MockVendor, "delete_vlan", _delete_also_fails)

    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 100, "name": "SSH_TEST", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "failed"
    assert job["retry_count"] == 4
    assert call_count["n"] == 4
    assert job["rollback_performed"] is True
    assert job["rollback_success"] is False

    entry = _latest_audit_entry(vlan_id=100)
    assert entry.status == "failure"
    assert entry.details.get("error_type") == "transient"


def test_permanent_device_rejection_fails_immediately_no_retries(operator_client, client, monkeypatch):
    monkeypatch.setattr(
        MockVendor, "create_vlan",
        lambda self, vlan_id, name, device, password: {"rc": 1, "stdout": "", "stderr": "VLAN already exists"},
    )

    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 501, "name": "DUPLICATE", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "failed"
    assert job["retry_count"] == 0
    assert "already exists" in job["error"]

    entry = _latest_audit_entry(vlan_id=501)
    assert entry.status == "failure"
    assert entry.details.get("error_type") == "permanent"


def test_normal_execution_succeeds_no_retries(operator_client, client):
    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 200, "name": "OK_VLAN", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"
    assert job["retry_count"] == 0

    entry = _latest_audit_entry(vlan_id=200)
    assert entry.status == "success"


def test_permanent_ansible_error_no_retries(operator_client, client, monkeypatch, restore_mock_vlans):
    call_count = {"n": 0}
    delete_count = {"n": 0}

    def _permanent_failure(self, vlan_id, name, device, password):
        call_count["n"] += 1
        _dejar_vlan_creada(vlan_id, name)
        return {"rc": 1, "stdout": "", "stderr": "VLAN configuration syntax error"}

    def _delete_also_fails(self, vlan_id, device, password):
        delete_count["n"] += 1
        return {"rc": 1, "stdout": "", "stderr": "VLAN configuration syntax error"}

    monkeypatch.setattr(MockVendor, "create_vlan", _permanent_failure)
    monkeypatch.setattr(MockVendor, "delete_vlan", _delete_also_fails)

    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 300, "name": "PERM_FAIL", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "failed"
    assert job["retry_count"] == 1
    assert call_count["n"] == 1
    assert job["rollback_performed"] is True
    assert job["rollback_success"] is False

    entry = _latest_audit_entry(vlan_id=300)
    assert entry.status == "failure"
    assert entry.details.get("error_type") == "permanent"


def test_retry_count_visible_during_execution(operator_client, client, monkeypatch):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda s: None)

    call_number = {"n": 0}

    def _transient_then_succeed(self, vlan_id, name, device, password):
        call_number["n"] += 1
        n = call_number["n"]
        if n <= 2:
            return {"rc": 1, "stdout": "SSH connection refused", "stderr": ""}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", _transient_then_succeed)

    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 400, "name": "RETRY_VIS", "devices": ["mock_device"]}
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    final = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert final["status"] == "completed"
    assert final["retry_count"] == 2
    assert final["last_error"] is not None
    assert "ssh" in final["last_error"].lower()
    assert call_number["n"] == 3
