import time

import pytest

from app.db.models import AuditLogModel
from app.db.session import get_session
from app.models.job import Job


@pytest.fixture(scope="session", autouse=True)
def _seed_mock_devices():
    from app.composition import device_repository, inventory, site_repository
    from app.core.exceptions import ValidationError

    existing = site_repository.list(name="Mock Site")
    site = existing[0] if existing else site_repository.crear_con_grupo_default("Mock Site", kind="REGULAR")
    if device_repository.get("mock_device") is None:
        try:
            inventory.register(
                name="mock_device", host="192.168.1.1", vendor="cisco_ios", platform="ios",
                username="admin", password="admin",
                site_id=site.id, device_group_id=site.default_group_id,
                actor={"username": "admin"},
            )
        except ValidationError:
            pass
    yield


@pytest.fixture(autouse=True)
def _force_mock_vendor_drivers(monkeypatch):
    from app.composition import plugin_registry
    from app.services.vendors.mock import MockVendor

    mock = MockVendor()
    for vendor in ("cisco_ios", "huawei_vrp"):
        monkeypatch.setitem(plugin_registry._vendors, vendor, mock)


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    import app.services.orquestador as orquestador_module
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda *_a, **_kw: None)


@pytest.fixture(autouse=True)
def clear_log():
    def _clear():
        with get_session() as session:
            session.query(AuditLogModel).delete(synchronize_session=False)

    _clear()
    yield
    _clear()


def _patch_create_vlan(monkeypatch, result: dict) -> None:
    from app.services.vendors.mock import MockVendor
    monkeypatch.setattr(MockVendor, "create_vlan", lambda self, vlan_id, name, device, password: result)


def test_successful_create_ends_completed(operator_client, admin_client):
    from app.composition import job_repository

    resp = operator_client.post("/api/v1/vlans/", json={"vlan_id": 601, "name": "OK", "devices": ["mock_device"]})
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    time.sleep(0.5)

    log = admin_client.get("/api/v1/audit/").json()["data"]["items"]
    entry = next(e for e in log if e["action"] == "crear_vlan")
    assert entry["status"] == "success"

    job = job_repository.get(job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.finished_at is not None


def test_duplicate_vlan_ends_failed_no_pending(operator_client, admin_client, monkeypatch):
    from app.composition import job_repository

    _patch_create_vlan(monkeypatch, {"rc": 1, "stdout": "", "stderr": "VLAN already exists"})

    resp = operator_client.post("/api/v1/vlans/", json={"vlan_id": 650, "name": "DUP", "devices": ["mock_device"]})
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    time.sleep(0.5)

    log = admin_client.get("/api/v1/audit/").json()["data"]["items"]
    entry = next(
        (e for e in log if e["action"] == "recurso_fallido" and e["device"] == "mock_device"),
        None,
    )
    assert entry is not None
    assert entry["status"] == "failure"

    job = job_repository.get(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.status != "pending"


def test_ssh_failure_updates_retry_count(operator_client, admin_client, monkeypatch):
    from app.composition import job_repository

    _patch_create_vlan(monkeypatch, {"rc": 1, "stdout": "", "stderr": "SSH connection timeout"})

    resp = operator_client.post("/api/v1/vlans/", json={"vlan_id": 602, "name": "SSH", "devices": ["mock_device"]})
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    time.sleep(0.5)

    log = admin_client.get("/api/v1/audit/").json()["data"]["items"]
    entry = next(e for e in log if e["action"] == "recurso_fallido" and e["device"] == "mock_device")
    assert entry["status"] == "failure"

    job = job_repository.get(job_id)
    assert job.status == "failed"
    assert job.retry_count > 0


def test_ensure_final_state_clears_stuck_pending():
    from app.composition import job_repository

    job = job_repository.add(Job(playbook="test.yml", device="phantom"))
    assert job.status == "pending"

    job.asegurar_estado_final()
    job_repository.add(job)

    updated = job_repository.get(job.job_id)
    assert updated.status == "failed"
    assert updated.error == "Unexpected termination"
    assert updated.finished_at is not None


def test_ensure_final_state_does_not_touch_completed():
    from app.composition import job_repository

    job = Job()
    job.marcar_iniciado()
    job.marcar_completado({"output": "ok"})
    job_repository.add(job)

    job.asegurar_estado_final()
    job_repository.add(job)

    updated = job_repository.get(job.job_id)
    assert updated.status == "completed"


def test_ensure_final_state_clears_stuck_running():
    from app.composition import job_repository

    job = Job()
    job.marcar_iniciado()
    job_repository.add(job)

    job.asegurar_estado_final()
    job_repository.add(job)

    updated = job_repository.get(job.job_id)
    assert updated.status == "failed"


def test_failed_job_has_structured_error_in_audit(operator_client, admin_client, monkeypatch):
    _patch_create_vlan(monkeypatch, {"rc": 1, "stdout": "", "stderr": "device unreachable"})

    operator_client.post("/api/v1/vlans/", json={"vlan_id": 603, "name": "ERR", "devices": ["mock_device"]})

    time.sleep(0.5)

    log = admin_client.get("/api/v1/audit/").json()["data"]["items"]
    entry = next(e for e in log if e["action"] == "recurso_fallido" and e["device"] == "mock_device")
    details = entry["details"]
    assert "unreachable" in details["error"]
    assert details.get("error_type") in ("permanent", "transient", "unknown")
    assert details.get("error_summary")


def test_jobs_endpoint_returns_all_created_jobs(operator_client, client):
    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 604, "name": "JOBCHECK", "devices": ["mock_device", "mock_device"]}
    )
    assert response.status_code == 202
    created_ids = {e["job_id"] for e in response.json()["data"]["jobs"]}

    all_jobs = {j["job_id"] for j in client.get("/api/v1/jobs/").json()["data"]["items"]}
    assert created_ids.issubset(all_jobs)


def test_job_fetchable_by_id_immediately_after_creation(operator_client, client):
    response = operator_client.post(
        "/api/v1/vlans/", json={"vlan_id": 605, "name": "IMMEDIATE", "devices": ["mock_device"]}
    )
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["job_id"] == job_id
