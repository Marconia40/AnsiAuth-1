import time

import pytest

from app.db.models import JobModel
from app.db.session import get_session
from app.models.job import Job


@pytest.fixture(scope="session", autouse=True)
def _seed_mock_devices():
    from app.composition import device_repository, inventory, site_repository
    from app.core.exceptions import ValidationError

    existing = site_repository.list(name="Mock Site")
    site = existing[0] if existing else site_repository.crear_con_grupo_default("Mock Site", kind="REGULAR")
    for name, host in (("mock_device", "192.168.1.1"), ("fail_device", "192.168.1.2")):
        if device_repository.get(name) is None:
            try:
                inventory.register(
                    name=name, host=host, vendor="cisco_ios", platform="ios",
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


def test_job_lifecycle(client):
    payload = {"vlan_id": 800, "name": "TESTJOB", "devices": ["mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["status"] in ["pending", "running", "completed"]

    time.sleep(1)

    response = client.get(f"/api/v1/jobs/{job_id}")
    data = response.json()
    assert data["data"]["status"] == "completed"
    assert data["data"]["finished_at"] is not None


def test_job_failed_execution(client):
    payload = {"vlan_id": 10, "name": "FAILTEST", "devices": ["fail_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    time.sleep(1)

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["status"] == "failed"
    assert data["data"]["error"] is not None


def test_job_not_found(client):
    response = client.get("/api/v1/jobs/nonexistent-job-id")
    assert response.status_code == 404


def test_list_jobs(client):
    response = client.get("/api/v1/jobs/")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert isinstance(data["items"], list)
    assert "total" in data
    assert "page" in data
    assert "page_size" in data


def test_cancel_job_success(client):
    from app.composition import job_repository

    job = job_repository.add(Job())
    response = client.post(f"/api/v1/jobs/{job.job_id}/cancel")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] == "cancelled"


def test_get_job_requires_auth(client, observer_client, unauth_client):
    from app.composition import job_repository

    job = job_repository.add(Job())

    response = unauth_client.get(f"/api/v1/jobs/{job.job_id}")
    assert response.status_code == 401

    response = unauth_client.get(
        f"/api/v1/jobs/{job.job_id}",
        headers={"Authorization": "Bearer this.is.an.expired.or.invalid.token"},
    )
    assert response.status_code == 401

    response = observer_client.get(f"/api/v1/jobs/{job.job_id}")
    assert response.status_code == 200

    response = client.get(f"/api/v1/jobs/{job.job_id}")
    assert response.status_code == 200


def test_cancel_job_invalid_state(client):
    payload = {"vlan_id": 60, "name": "DONETEST", "devices": ["mock_device"]}
    response = client.post("/api/v1/vlans/", json=payload)
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    time.sleep(1)

    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 409


def test_job_persisted_to_db(client):
    response = client.post("/api/v1/vlans/", json={"vlan_id": 700, "name": "PERSIST_JOB", "devices": ["mock_device"]})
    assert response.status_code == 202
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    with get_session() as session:
        row = session.query(JobModel).filter_by(job_id=job_id).first()
        assert row is not None
        assert row.job_id == job_id
        assert row.device == "mock_device"


def test_job_status_updates_reflected_in_db(client):
    response = client.post("/api/v1/vlans/", json={"vlan_id": 701, "name": "STATUS_CHECK", "devices": ["mock_device"]})
    job_id = response.json()["data"]["jobs"][0]["job_id"]

    with get_session() as session:
        row = session.query(JobModel).filter_by(job_id=job_id).first()
        assert row.status == "completed"
        assert row.finished_at is not None


def test_mark_orphaned_jobs_failed():
    from app.composition import job_repository

    job = Job(playbook="test.yml", device="phantom")
    job.marcar_iniciado()
    job_repository.add(job)

    count = job_repository.recuperar_huerfanos()
    assert count >= 1

    recovered = job_repository.get(job.job_id)
    assert recovered.status == "failed"
    assert recovered.error is not None
    assert recovered.finished_at is not None


def test_mark_orphaned_jobs_skips_terminal_states():
    from app.composition import job_repository

    done = Job()
    done.marcar_iniciado()
    done.marcar_completado({"output": "ok"})
    job_repository.add(done)

    cancelled = Job()
    cancelled.cancelar()
    job_repository.add(cancelled)

    job_repository.recuperar_huerfanos()

    assert job_repository.get(done.job_id).status == "completed"
    assert job_repository.get(cancelled.job_id).status == "cancelled"
