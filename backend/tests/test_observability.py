import logging

import app.services.orquestador as orquestador_module
from app.composition import (
    audit_repository,
    device_repository,
    device_sync_service,
    inventory,
    job_repository,
    plugin_registry,
    site_repository,
)
from app.core.exceptions import ValidationError as _ValidationError
from app.models.job import Job
from app.models.visibility_scope import VisibilityScope
from app.services.vendors.mock import MockVendor


def _create_parcial_y_falla(self, vlan_id, name, device, password):
    from app.models.vlan import VLAN
    from app.services.vendors.mock import _mock_vlans

    _mock_vlans.append(VLAN(vlan_id=vlan_id, name=name))
    return {"rc": 1, "stdout": "", "stderr": "configuration syntax error"}


def _delete_que_borra(self, vlan_id, device, password):
    from app.services.vendors.mock import _mock_vlans

    _mock_vlans[:] = [v for v in _mock_vlans if v.vlan_id != vlan_id]
    return {"rc": 0, "stdout": "deleted", "stderr": ""}


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


def test_execution_summary_present_on_success(client):
    resp = client.post(
        "/api/v1/vlans/",
        json={"vlan_id": 700, "name": "OBS_VLAN", "devices": ["mock_device"]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"
    summary = job["execution_summary"]
    assert summary is not None
    assert summary["attempts"] == 1
    assert summary["rollback_performed"] is False
    assert summary["rollback_success"] is None
    assert summary["duration_ms"] is not None
    assert summary["duration_ms"] >= 0


def test_execution_summary_attempts_after_retries(client, monkeypatch):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda s: None)

    call_number = {"n": 0}

    def _transient_then_succeed(self, vlan_id, name, device, password):
        call_number["n"] += 1
        if call_number["n"] <= 2:
            return {"rc": 1, "stdout": "SSH connection refused", "stderr": ""}
        return {"rc": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(MockVendor, "create_vlan", _transient_then_succeed)

    resp = client.post(
        "/api/v1/vlans/",
        json={"vlan_id": 701, "name": "RETRY_OBS", "devices": ["mock_device"]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"
    assert job["retry_count"] == 2
    summary = job["execution_summary"]
    assert summary["attempts"] == 3
    assert summary["duration_ms"] is not None


def test_execution_summary_on_failed_with_rollback(client, monkeypatch, restore_mock_vlans):
    monkeypatch.setattr(MockVendor, "create_vlan", _create_parcial_y_falla)
    monkeypatch.setattr(MockVendor, "delete_vlan", _delete_que_borra)

    resp = client.post(
        "/api/v1/vlans/",
        json={"vlan_id": 901, "name": "ROLLBACK_OBS", "devices": ["mock_device"]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "failed"
    summary = job["execution_summary"]
    assert summary["rollback_performed"] is True
    assert summary["rollback_success"] is True
    assert summary["attempts"] == 1


def test_execution_summary_attempts_none_for_pending_job(client):
    job = Job(operation="vlan", device="mock_device", parameters={})
    job_repository.add(job)

    resp = client.get(f"/api/v1/jobs/{job.job_id}").json()["data"]
    assert resp["status"] == "pending"
    assert resp["execution_summary"]["attempts"] is None


def test_current_step_rollback_completed_after_failure(client, monkeypatch, restore_mock_vlans):
    monkeypatch.setattr(MockVendor, "create_vlan", _create_parcial_y_falla)
    monkeypatch.setattr(MockVendor, "delete_vlan", _delete_que_borra)

    resp = client.post(
        "/api/v1/vlans/",
        json={"vlan_id": 902, "name": "STEP_OBS", "devices": ["mock_device"]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "failed"
    assert job["rollback_performed"] is True
    assert job["current_step"] == "failed"


def test_current_step_completed_on_success(client):
    resp = client.post(
        "/api/v1/vlans/",
        json={"vlan_id": 703, "name": "STEP_OK", "devices": ["mock_device"]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["jobs"][0]["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed"
    assert job["current_step"] == "completed"


def test_current_step_is_executing_immediately_after_marcar_iniciado():
    job = Job()
    job.marcar_iniciado()
    assert job.status == "running"
    assert job.current_step == "executing"


def test_retry_wait_duration_in_log(monkeypatch, caplog):
    from app.composition import orquestador

    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    def _transient():
        return {"rc": 1, "stdout": "SSH connection refused", "stderr": ""}

    with caplog.at_level(logging.INFO, logger="app.services.orquestador"):
        orquestador._ejecutar_con_retry(_transient, Job(), "timing-test-device", max_retries=1, retry_base_delay=2.0)

    retry_lines = [r.message for r in caplog.records if "reintentando" in r.message]
    assert len(retry_lines) == 1
    assert "delay=2.00s" in retry_lines[0]


def test_retry_log_includes_device_name(monkeypatch, caplog):
    from app.composition import orquestador

    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    def _transient():
        return {"rc": 1, "stdout": "SSH connection refused", "stderr": ""}

    with caplog.at_level(logging.INFO, logger="app.services.orquestador"):
        orquestador._ejecutar_con_retry(_transient, Job(), "switch1", max_retries=1, retry_base_delay=0.01)

    retry_lines = [r.message for r in caplog.records if "reintentando" in r.message]
    assert len(retry_lines) == 1
    assert "switch1" in retry_lines[0]


def test_group_job_summary_partial_success_false_when_all_succeed():
    import uuid
    group_job_id = str(uuid.uuid4())
    for device in ("sw1", "sw2"):
        j = Job(operation="vlan", device=device, group_job_id=group_job_id)
        j.marcar_iniciado()
        j.marcar_completado({"rc": 0})
        job_repository.add(j)

    resumen = job_repository.resumen_de_grupo(group_job_id)
    assert resumen["execution_summary"]["partial_success"] is False


def test_group_job_summary_partial_success_true_on_mixed():
    import uuid
    group_job_id = str(uuid.uuid4())
    j1 = Job(operation="vlan", device="sw1", group_job_id=group_job_id)
    j1.marcar_iniciado()
    j1.marcar_completado({"rc": 0})
    job_repository.add(j1)

    j2 = Job(operation="vlan", device="sw2", group_job_id=group_job_id)
    j2.marcar_iniciado()
    j2.marcar_fallido("boom")
    job_repository.add(j2)

    resumen = job_repository.resumen_de_grupo(group_job_id)
    assert resumen["execution_summary"]["partial_success"] is True


def test_group_job_summary_duration_ms_set_after_completion():
    import uuid
    group_job_id = str(uuid.uuid4())
    j = Job(operation="vlan", device="sw1", group_job_id=group_job_id)
    j.marcar_iniciado()
    j.marcar_completado({"rc": 0})
    job_repository.add(j)

    resumen = job_repository.resumen_de_grupo(group_job_id)
    s = resumen["execution_summary"]
    assert s["duration_ms"] is not None
    assert isinstance(s["duration_ms"], int)
    assert s["duration_ms"] >= 0


def test_group_job_summary_duration_ms_none_while_pending():
    import uuid
    group_job_id = str(uuid.uuid4())
    j = Job(operation="vlan", device="sw1", group_job_id=group_job_id)
    job_repository.add(j)

    resumen = job_repository.resumen_de_grupo(group_job_id)
    assert resumen["execution_summary"]["duration_ms"] is None


def test_api_group_job_summary_includes_partial_success_and_duration(client):
    payload = {"vlan_id": 803, "name": "OBSGRP", "devices": ["mock_device"]}
    create_resp = client.post("/api/v1/vlans/", json=payload)
    assert create_resp.status_code == 202
    group_job_id = create_resp.json()["data"]["group_job_id"]

    resp = client.get(f"/api/v1/group-jobs/{group_job_id}")
    assert resp.status_code == 200
    s = resp.json()["data"]["execution_summary"]
    assert "partial_success" in s
    assert "duration_ms" in s
    assert isinstance(s["partial_success"], bool)


def test_api_per_device_result_fields_complete(client):
    payload = {"vlan_id": 820, "name": "DEVFLDS", "devices": ["mock_device"]}
    create_resp = client.post("/api/v1/vlans/", json=payload)
    assert create_resp.status_code == 202
    group_job_id = create_resp.json()["data"]["group_job_id"]

    resp = client.get(f"/api/v1/group-jobs/{group_job_id}")
    assert resp.status_code == 200
    dr = resp.json()["data"]["device_results"][0]
    for field in ("device", "status", "retry_count", "rollback_performed", "rollback_success", "duration_ms"):
        assert field in dr, f"Missing field: {field}"
