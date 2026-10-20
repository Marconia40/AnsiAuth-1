import time

import pytest


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


def test_create_vlan_response_includes_group_job_id(client):
    payload = {"vlan_id": 310, "name": "GRPTEST", "devices": ["mock_device"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert "group_job_id" in data
    assert data["group_job_id"] is not None
    assert len(data["jobs"]) == 1


def test_create_vlan_multi_device_group_job_id(client):
    from app.composition import inventory, site_repository
    from app.core.exceptions import ValidationError

    site = site_repository.crear_con_grupo_default("Group Job Test Site A", kind="REGULAR")
    for name, host in [("grp_dev1", "10.99.1.1"), ("grp_dev2", "10.99.1.2")]:
        try:
            inventory.register(
                name=name, host=host, vendor="cisco_ios", platform="ios",
                username="admin", password="pass",
                site_id=site.id, device_group_id=site.default_group_id,
                actor={"username": "admin"},
            )
        except ValidationError:
            pass
    payload = {"vlan_id": 311, "name": "GRPMULTI", "devices": ["grp_dev1", "grp_dev2"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert "group_job_id" in data
    assert len(data["jobs"]) == 2


def test_delete_vlan_response_includes_group_job_id(client):
    client.post("/api/v1/vlans/", json={"vlan_id": 312, "name": "DELGRP", "devices": ["mock_device"]})
    time.sleep(0.2)
    resp = client.request("DELETE", "/api/v1/vlans/312", json={"devices": ["mock_device"]})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert "group_job_id" in data
    assert data["group_job_id"] is not None


def test_update_vlan_response_includes_group_job_id(client):
    client.post("/api/v1/vlans/", json={"vlan_id": 313, "name": "UPDGRP", "devices": ["mock_device"]})
    time.sleep(0.2)
    resp = client.patch("/api/v1/vlans/313", json={"description": "Updated", "devices": ["mock_device"]})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert "group_job_id" in data
    assert data["group_job_id"] is not None


def test_get_group_job_endpoint(client):
    payload = {"vlan_id": 320, "name": "GETGRP", "devices": ["mock_device"]}
    create_resp = client.post("/api/v1/vlans/", json=payload)
    assert create_resp.status_code == 202
    group_job_id = create_resp.json()["data"]["group_job_id"]

    time.sleep(0.3)

    resp = client.get(f"/api/v1/group-jobs/{group_job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    gj = data["data"]
    assert gj["group_job_id"] == group_job_id
    assert gj["operation"] == "vlan"
    assert "execution_summary" in gj
    assert "device_results" in gj
    assert len(gj["device_results"]) == 1
    s = gj["execution_summary"]
    assert "total_devices" in s
    assert "completed" in s
    assert "failed" in s
    assert "rollback_count" in s


def test_get_group_job_not_found(client):
    resp = client.get("/api/v1/group-jobs/does-not-exist")
    assert resp.status_code == 404


def test_get_group_job_unauthenticated(unauth_client):
    resp = unauth_client.get("/api/v1/group-jobs/anything")
    assert resp.status_code == 401


def test_job_response_includes_group_job_id(client):
    payload = {"vlan_id": 330, "name": "JOBGRP", "devices": ["mock_device"]}
    create_resp = client.post("/api/v1/vlans/", json=payload)
    assert create_resp.status_code == 202
    created = create_resp.json()["data"]
    job_id = created["jobs"][0]["job_id"]
    group_job_id = created["group_job_id"]

    time.sleep(0.3)

    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    job_data = resp.json()["data"]
    assert job_data["group_job_id"] == group_job_id


def test_group_job_device_results_populated_after_execution(client):
    payload = {"vlan_id": 340, "name": "EXECGRP", "devices": ["mock_device"]}
    create_resp = client.post("/api/v1/vlans/", json=payload)
    group_job_id = create_resp.json()["data"]["group_job_id"]

    time.sleep(0.5)

    resp = client.get(f"/api/v1/group-jobs/{group_job_id}")
    gj = resp.json()["data"]
    assert gj["status"] in ("completed", "failed", "partial_success")
    assert len(gj["device_results"]) == 1
    dr = gj["device_results"][0]
    assert dr["device"] == "mock_device"
    assert dr["job_id"] is not None
    assert dr["status"] in ("completed", "failed")


def test_group_job_multi_device_all_completed_aggregation(client):
    from app.composition import inventory, site_repository
    from app.core.exceptions import ValidationError

    site = site_repository.crear_con_grupo_default("Group Job Test Site B", kind="REGULAR")
    for name, host in [("agg_dev1", "10.99.2.1"), ("agg_dev2", "10.99.2.2")]:
        try:
            inventory.register(
                name=name, host=host, vendor="cisco_ios", platform="ios",
                username="admin", password="pass",
                site_id=site.id, device_group_id=site.default_group_id,
                actor={"username": "admin"},
            )
        except ValidationError:
            pass
    payload = {"vlan_id": 341, "name": "MULTAGG", "devices": ["agg_dev1", "agg_dev2"]}
    create_resp = client.post("/api/v1/vlans/", json=payload)
    group_job_id = create_resp.json()["data"]["group_job_id"]

    time.sleep(0.7)

    resp = client.get(f"/api/v1/group-jobs/{group_job_id}")
    gj = resp.json()["data"]
    assert gj["status"] in ("completed", "failed", "partial_success")
    s = gj["execution_summary"]
    assert s["total_devices"] == 2
    assert s["completed"] + s["failed"] == 2


def test_backward_compat_single_device_create(client):
    payload = {"vlan_id": 350, "name": "COMPAT", "devices": ["mock_device"]}
    resp = client.post("/api/v1/vlans/", json=payload)
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert resp.json()["success"] is True
    assert isinstance(data["jobs"], list)
    assert len(data["jobs"]) == 1
    assert "job_id" in data["jobs"][0]
    assert "group_job_id" in data


def _cliente_con_grant(site_id: int | None):
    import uuid
    from fastapi.testclient import TestClient
    from app.core.security import create_access_token
    from app.db.models import RoleAssignmentModel, UserModel
    from app.db.session import get_session
    from app.main import app

    username = f"gj-scope-{uuid.uuid4().hex[:6]}"
    with get_session() as session:
        user = UserModel(username=username, hashed_password="x", is_system_admin=False)
        session.add(user)
        session.flush()
        if site_id is not None:
            session.add(RoleAssignmentModel(
                user_id=user.id, site_id=site_id, device_group_id=None, role="observer",
            ))
        user_id = user.id
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {create_access_token({'sub': username})}"})
    return c, user_id


def test_group_job_only_aggregates_devices_in_scope(client):
    from app.composition import inventory, site_repository
    from app.core.exceptions import ValidationError
    from app.db.models import RoleAssignmentModel, UserModel
    from app.db.session import get_session

    sitios = {}
    for sufijo, host in (("A", "10.99.4.1"), ("B", "10.99.4.2")):
        nombre = f"Group Job Scope Site {sufijo}"
        existentes = site_repository.list(name=nombre)
        site = existentes[0] if existentes else site_repository.crear_con_grupo_default(nombre, kind="REGULAR")
        sitios[sufijo] = site
        try:
            inventory.register(
                name=f"gjscope_{sufijo.lower()}", host=host, vendor="cisco_ios", platform="ios",
                username="admin", password="pass",
                site_id=site.id, device_group_id=site.default_group_id,
                actor={"username": "admin"},
            )
        except ValidationError:
            pass

    resp = client.post("/api/v1/vlans/", json={
        "vlan_id": 361, "name": "GJSCOPE", "devices": ["gjscope_a", "gjscope_b"],
    })
    assert resp.status_code == 202
    group_job_id = resp.json()["data"]["group_job_id"]

    observer_a, uid_a = _cliente_con_grant(sitios["A"].id)
    sin_grants, uid_n = _cliente_con_grant(None)
    try:
        r = observer_a.get(f"/api/v1/group-jobs/{group_job_id}")
        assert r.status_code == 200, r.text
        gj = r.json()["data"]
        assert [d["device"] for d in gj["device_results"]] == ["gjscope_a"]
        assert gj["execution_summary"]["total_devices"] == 1

        r = sin_grants.get(f"/api/v1/group-jobs/{group_job_id}")
        assert r.status_code == 404, r.text

        r = client.get(f"/api/v1/group-jobs/{group_job_id}")
        assert r.json()["data"]["execution_summary"]["total_devices"] == 2
    finally:
        with get_session() as session:
            session.query(RoleAssignmentModel).filter(
                RoleAssignmentModel.user_id.in_([uid_a, uid_n])
            ).delete(synchronize_session=False)
            session.query(UserModel).filter(
                UserModel.id.in_([uid_a, uid_n])
            ).delete(synchronize_session=False)
