from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.models import (
    AuditLogModel,
    RoleAssignmentModel,
    SiteModel,
    UserModel,
)
from app.db.session import get_session
from app.main import app


@pytest.fixture()
def audit_scaffold():
    tag = uuid.uuid4().hex[:6]
    site_a_name = f"aud-A-{tag}"
    site_b_name = f"aud-B-{tag}"
    user_name = f"aud-user-{tag}"

    site_a_id = site_b_id = user_id = None
    with get_session() as session:
        for name in (site_a_name, site_b_name):
            s = SiteModel(name=name, kind="REGULAR")
            session.add(s)
            session.flush()
            if name == site_a_name:
                site_a_id = s.id
            else:
                site_b_id = s.id
        user = UserModel(
            username=user_name, hashed_password="x",
            is_system_admin=False,
        )
        session.add(user)
        session.flush()
        user_id = user.id
        session.add(RoleAssignmentModel(
            user_id=user.id, site_id=site_a_id,
            device_group_id=None, role="observer",
        ))
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        for sid in (site_a_id, site_b_id):
            session.add(AuditLogModel(
                timestamp=now, user="admin", action="update_site",
                resource="site", resource_id=str(sid),
                status="success", details={"site_id": sid},
            ))
        session.add(AuditLogModel(
            timestamp=now, user=user_name, action="login",
            resource="auth", resource_id=None,
            status="success", details={"username": user_name},
        ))

    token = create_access_token({"sub": user_name, "role": "observer"})
    observer_client = TestClient(app)
    observer_client.headers.update({"Authorization": f"Bearer {token}"})

    scaffold = {
        "site_a_id": site_a_id, "site_b_id": site_b_id,
        "user_id": user_id, "user_name": user_name,
        "observer_client": observer_client,
    }
    yield scaffold

    with get_session() as session:
        session.query(AuditLogModel).filter(
            AuditLogModel.resource_id.in_([str(site_a_id), str(site_b_id)])
        ).delete(synchronize_session=False)
        session.query(AuditLogModel).filter(
            AuditLogModel.user == user_name,
        ).delete(synchronize_session=False)
        session.query(RoleAssignmentModel).filter_by(user_id=user_id).delete(
            synchronize_session=False,
        )
        session.query(UserModel).filter_by(id=user_id).delete(synchronize_session=False)
        session.query(SiteModel).filter(
            SiteModel.id.in_([site_a_id, site_b_id])
        ).delete(synchronize_session=False)


def test_system_admin_sees_all_audit_rows(admin_client, audit_scaffold):
    s = audit_scaffold
    r = admin_client.get("/api/v1/audit/")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]["items"]
    ids_seen = {row["resource_id"] for row in rows if row["resource"] == "site"}
    assert str(s["site_a_id"]) in ids_seen
    assert str(s["site_b_id"]) in ids_seen


def test_observer_sees_only_scoped_rows(audit_scaffold):
    s = audit_scaffold
    r = s["observer_client"].get("/api/v1/audit/")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]["items"]
    site_ids_seen = {row["resource_id"] for row in rows if row["resource"] == "site"}
    assert str(s["site_a_id"]) in site_ids_seen, (
        f"Expected site A's audit row; got {site_ids_seen}"
    )
    assert str(s["site_b_id"]) not in site_ids_seen, (
        f"Site B is outside the observer's scope; got {site_ids_seen}"
    )


def test_observer_still_sees_own_auth_events(audit_scaffold):
    s = audit_scaffold
    r = s["observer_client"].get("/api/v1/audit/")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]["items"]
    assert any(
        row["resource"] == "auth" and row["user"] == s["user_name"]
        for row in rows
    ), "observer should see their own login row"


def test_observer_does_not_see_other_users_auth_events(audit_scaffold):
    import datetime as _dt

    s = audit_scaffold
    otro = f"otro-{uuid.uuid4().hex[:6]}"
    with get_session() as session:
        session.add(AuditLogModel(
            timestamp=_dt.datetime.now(_dt.timezone.utc), user=otro,
            action="login", resource="auth", resource_id=None,
            status="failed", details={"username": otro},
        ))
    try:
        r = s["observer_client"].get("/api/v1/audit/", params={"limit": 1000})
        assert r.status_code == 200, r.text
        auth_users = {
            row["user"] for row in r.json()["data"]["items"] if row["resource"] == "auth"
        }
        assert auth_users == {s["user_name"]}, auth_users
    finally:
        with get_session() as session:
            session.query(AuditLogModel).filter(
                AuditLogModel.user == otro,
            ).delete(synchronize_session=False)


def test_admin_sees_every_users_auth_events(admin_client, audit_scaffold):
    s = audit_scaffold
    r = admin_client.get("/api/v1/audit/", params={"resource": "auth", "limit": 1000})
    assert r.status_code == 200, r.text
    assert any(row["user"] == s["user_name"] for row in r.json()["data"]["items"])


def test_observer_sees_resource_rows_of_devices_in_scope(audit_scaffold):
    import datetime as _dt

    from app.db.models import DeviceGroupModel, DeviceModel

    s = audit_scaffold
    tag = uuid.uuid4().hex[:6]
    nombres = {}
    with get_session() as session:
        for clave, sid in (("a", s["site_a_id"]), ("b", s["site_b_id"])):
            grupo = DeviceGroupModel(name=f"aud-g{clave}-{tag}", site_id=sid, is_default=False)
            session.add(grupo)
            session.flush()
            nombre = f"aud-dev-{clave}-{tag}"
            session.add(DeviceModel(
                name=nombre, host="10.0.0.1", vendor="cisco", platform="ios",
                username="u", encrypted_password="x", device_group_id=grupo.id,
            ))
            session.flush()
            session.add(AuditLogModel(
                timestamp=_dt.datetime.now(_dt.timezone.utc), user="admin",
                action="create_vlan", resource="vlan", device=nombre,
                status="success", details={},
            ))
            nombres[clave] = nombre
    try:
        r = s["observer_client"].get("/api/v1/audit/", params={"resource": "vlan", "limit": 1000})
        assert r.status_code == 200, r.text
        devices = {row["device"] for row in r.json()["data"]["items"]}
        assert nombres["a"] in devices
        assert nombres["b"] not in devices
    finally:
        with get_session() as session:
            session.query(AuditLogModel).filter(
                AuditLogModel.device.in_(nombres.values()),
            ).delete(synchronize_session=False)
            session.query(DeviceModel).filter(
                DeviceModel.name.in_(nombres.values()),
            ).delete(synchronize_session=False)
            session.query(DeviceGroupModel).filter(
                DeviceGroupModel.name.like(f"aud-g%-{tag}"),
            ).delete(synchronize_session=False)
