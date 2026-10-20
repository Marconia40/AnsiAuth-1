from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.rls_context import current_user_ctx, sin_contexto_de_sistema, system_context
from app.db.models import (
    DeviceGroupModel,
    DeviceModel,
    RoleAssignmentModel,
    SiteModel,
    UserModel,
)
from app.db.session import get_engine, get_session


BASE_INFRA_KIND = "BASE_INFRASTRUCTURE"


def _is_postgres() -> bool:
    try:
        return get_engine().dialect.name == "postgresql"
    except Exception:
        return False


def _connecting_role_bypasses_rls() -> bool:
    if not _is_postgres():
        return False
    try:
        with get_session() as session:
            row = session.execute(text(
                "SELECT rolsuper OR rolbypassrls "
                "  FROM pg_roles WHERE rolname = current_user"
            )).scalar()
            return bool(row)
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(
        not _is_postgres(),
        reason="RLS is Postgres-only; run with DATABASE_URL pointing at Postgres",
    ),
    pytest.mark.skipif(
        _connecting_role_bypasses_rls(),
        reason=(
            "connecting role is SUPERUSER or has BYPASSRLS — RLS silently "
            "skipped. Use a non-super app role to exercise these tests. See "
            "docs/upgrades/phases/phase-6-rls-and-optional.md."
        ),
    ),
]


@pytest.fixture(autouse=True)
def _como_usuario():
    token = current_user_ctx.set({})
    with sin_contexto_de_sistema():
        yield
    current_user_ctx.reset(token)


@pytest.fixture()
def rls_scaffold():
    tag = uuid.uuid4().hex[:6]
    site_a_name = f"rls-A-{tag}"
    site_b_name = f"rls-B-{tag}"
    dev_a_name = f"rls-dev-A-{tag}"
    dev_b_name = f"rls-dev-B-{tag}"
    user_name = f"rls-user-{tag}"

    with system_context():
        with get_session() as session:
            site_a = SiteModel(name=site_a_name, kind="REGULAR")
            site_b = SiteModel(name=site_b_name, kind="REGULAR")
            session.add_all([site_a, site_b])
            session.flush()
            group_a = DeviceGroupModel(name=f"Default-{tag}-A", site_id=site_a.id, is_default=True)
            group_b = DeviceGroupModel(name=f"Default-{tag}-B", site_id=site_b.id, is_default=True)
            session.add_all([group_a, group_b])
            session.flush()
            site_a.default_group_id = group_a.id
            site_b.default_group_id = group_b.id
            dev_a = DeviceModel(
                name=dev_a_name, host="10.0.0.1", vendor="cisco", platform="ios",
                username="u", encrypted_password="x", device_group_id=group_a.id,
            )
            dev_b = DeviceModel(
                name=dev_b_name, host="10.0.0.2", vendor="cisco", platform="ios",
                username="u", encrypted_password="x", device_group_id=group_b.id,
            )
            session.add_all([dev_a, dev_b])
            user = UserModel(
                username=user_name, hashed_password="x", is_system_admin=False,
            )
            session.add(user)
            session.flush()
            session.add(RoleAssignmentModel(
                user_id=user.id, site_id=site_a.id, device_group_id=None, role="observer",
            ))
            session.flush()
            scaffold = {
                "user_id": user.id,
                "user_name": user_name,
                "site_a_id": site_a.id, "site_b_id": site_b.id,
                "group_a_id": group_a.id, "group_b_id": group_b.id,
                "dev_a_name": dev_a_name, "dev_b_name": dev_b_name,
                "site_a_name": site_a_name, "site_b_name": site_b_name,
                "site_ids": [site_a.id, site_b.id],
            }

    yield scaffold

    with system_context():
        with get_session() as session:
            session.query(RoleAssignmentModel).filter_by(user_id=scaffold["user_id"]).delete(
                synchronize_session=False
            )
            session.query(DeviceModel).filter(
                DeviceModel.name.in_([scaffold["dev_a_name"], scaffold["dev_b_name"]])
            ).delete(synchronize_session=False)
            for sid in scaffold["site_ids"]:
                row = session.query(SiteModel).filter_by(id=sid).first()
                if row is not None:
                    row.default_group_id = None
            session.flush()
            session.query(DeviceGroupModel).filter(
                DeviceGroupModel.site_id.in_(scaffold["site_ids"])
            ).delete(synchronize_session=False)
            session.query(SiteModel).filter(
                SiteModel.id.in_(scaffold["site_ids"])
            ).delete(synchronize_session=False)
            session.query(UserModel).filter_by(id=scaffold["user_id"]).delete(
                synchronize_session=False
            )


def _set_observer_context(user_id: int):
    current_user_ctx.set({"id": user_id, "is_system_admin": False})


def test_non_system_admin_sees_only_granted_sites(rls_scaffold):
    _set_observer_context(rls_scaffold["user_id"])
    with get_session() as session:
        visible_ids = {
            row[0] for row in session.query(SiteModel.id).filter(
                SiteModel.id.in_(rls_scaffold["site_ids"])
            ).all()
        }
    assert visible_ids == {rls_scaffold["site_a_id"]}, (
        "observer with a grant only on site A must not see site B"
    )


def test_non_system_admin_sees_only_granted_groups(rls_scaffold):
    _set_observer_context(rls_scaffold["user_id"])
    with get_session() as session:
        visible_ids = {
            row[0] for row in session.query(DeviceGroupModel.id).filter(
                DeviceGroupModel.id.in_([
                    rls_scaffold["group_a_id"], rls_scaffold["group_b_id"],
                ])
            ).all()
        }
    assert visible_ids == {rls_scaffold["group_a_id"]}


def test_non_system_admin_sees_only_granted_devices(rls_scaffold):
    _set_observer_context(rls_scaffold["user_id"])
    with get_session() as session:
        visible_names = {
            row[0] for row in session.query(DeviceModel.name).filter(
                DeviceModel.name.in_([
                    rls_scaffold["dev_a_name"], rls_scaffold["dev_b_name"],
                ])
            ).all()
        }
    assert visible_names == {rls_scaffold["dev_a_name"]}


def test_base_infra_invisible_to_non_system_admin_even_with_grant(rls_scaffold):
    with system_context():
        with get_session() as session:
            base = session.query(SiteModel).filter_by(kind=BASE_INFRA_KIND).first()
            assert base is not None
            base_id = base.id
            session.query(RoleAssignmentModel).filter_by(
                user_id=rls_scaffold["user_id"], site_id=base_id,
            ).delete(synchronize_session=False)
            session.add(RoleAssignmentModel(
                user_id=rls_scaffold["user_id"], site_id=base_id,
                device_group_id=None, role="observer",
            ))
    try:
        _set_observer_context(rls_scaffold["user_id"])
        with get_session() as session:
            row = (
                session.query(SiteModel.id)
                .filter(SiteModel.id == base_id)
                .first()
            )
        assert row is None, (
            "D14: Base Infra must be invisible to non-system-admins even with a stray grant"
        )
    finally:
        with system_context():
            with get_session() as session:
                session.query(RoleAssignmentModel).filter_by(
                    user_id=rls_scaffold["user_id"], site_id=base_id,
                ).delete(synchronize_session=False)


def test_system_admin_sees_every_site(rls_scaffold):
    current_user_ctx.set({"id": rls_scaffold["user_id"], "is_system_admin": True})
    with get_session() as session:
        visible_ids = {
            row[0] for row in session.query(SiteModel.id).filter(
                SiteModel.id.in_(rls_scaffold["site_ids"])
            ).all()
        }
    assert visible_ids == set(rls_scaffold["site_ids"]), (
        "system-admin must see every site regardless of grants"
    )


def test_system_admin_sees_base_infra(rls_scaffold):
    current_user_ctx.set({"id": rls_scaffold["user_id"], "is_system_admin": True})
    with get_session() as session:
        row = (
            session.query(SiteModel.id)
            .filter(SiteModel.kind == BASE_INFRA_KIND)
            .first()
        )
    assert row is not None, "system-admin must see Base Infra"


def test_raw_select_cannot_leak_other_site_devices(rls_scaffold):
    _set_observer_context(rls_scaffold["user_id"])
    with get_session() as session:
        all_devices = session.execute(
            text("SELECT name FROM devices WHERE name IN (:a, :b)"),
            {"a": rls_scaffold["dev_a_name"], "b": rls_scaffold["dev_b_name"]},
        ).all()
    names = {row[0] for row in all_devices}
    assert names == {rls_scaffold["dev_a_name"]}, (
        "RLS must block the observer from seeing site B's device even via "
        "a raw SELECT that bypasses app-layer scope filtering"
    )
