import os

os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "True")

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://ansiauth:ansiauth_dev_password@localhost:5432/ansiauth_test",
)
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_key_not_for_production"
os.environ.setdefault("COOKIE_SECURE", "false")

_db_url = os.environ["DATABASE_URL"]
if _db_url.startswith("sqlite") and "://./" in _db_url.replace("sqlite:///", "sqlite:///./"):
    if os.path.exists("./test.db"):
        os.remove("./test.db")
elif _db_url.startswith("postgresql"):
    from urllib.parse import urlparse as _urlparse
    _db_name = (_urlparse(_db_url).path or "").lstrip("/")
    if "test" not in _db_name.lower():
        raise RuntimeError(
            f"Refusing to run tests against database {_db_name!r} (from "
            f"DATABASE_URL) -- its name doesn't contain 'test'. This guard "
            f"exists because this exact mistake already wiped the real dev "
            f"database once (conftest.py runs DROP SCHEMA CASCADE). Point "
            f"DATABASE_URL at a dedicated test database, e.g. "
            f"postgresql://.../ansiauth_test, before running pytest."
        )
    import sqlalchemy as _sa
    _engine = _sa.create_engine(_db_url)
    with _engine.begin() as _conn:
        _conn.execute(_sa.text("DROP SCHEMA public CASCADE"))
        _conn.execute(_sa.text("CREATE SCHEMA public"))
    _engine.dispose()

from alembic import command as _alembic_command
from alembic.config import Config as _AlembicConfig

_alembic_cfg = _AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
_alembic_command.upgrade(_alembic_cfg, "head")

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app
from app.core.rls_context import install_worker_system_context

install_worker_system_context()


def elevated_headers(role: str) -> dict:
    from app.core.security import create_elevated_token
    return {"X-Elevated-Auth": create_elevated_token(role)}


def _make_client(role: str) -> TestClient:
    is_system_admin = role in {"admin", "super-admin"}
    token = create_access_token({"sub": role, "is_system_admin": is_system_admin})
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    yield
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture(autouse=True)
def _known_hosts_aislados(tmp_path, monkeypatch):
    from app.services import known_hosts

    monkeypatch.setattr(known_hosts, "KNOWN_HOSTS_DIRECTO", str(tmp_path / "known_hosts_directo"))
    monkeypatch.setattr(known_hosts, "KNOWN_HOSTS_ANSIBLE", str(tmp_path / "known_hosts"))


@pytest.fixture
def client():
    return _make_client("admin")


@pytest.fixture
def restore_mock_vlans():
    from app.models.vlan import VLAN
    from app.services.vendors import mock

    guardadas = [VLAN(vlan_id=v.vlan_id, name=v.name, status=v.status) for v in mock._mock_vlans]
    yield
    mock._mock_vlans[:] = guardadas


@pytest.fixture
def admin_client():
    return _make_client("admin")


@pytest.fixture
def operator_client():
    return _make_client("operator")


@pytest.fixture
def observer_client():
    return _make_client("observer")


@pytest.fixture
def super_admin_client():
    return _make_client("super-admin")


@pytest.fixture
def unauth_client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_vlan_mock():
    from app.services.vendors.mock import reset_mock_vlans
    reset_mock_vlans()
    yield
    reset_mock_vlans()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from app.composition import redis_coordinator
    redis_coordinator.resetear()
    yield
    redis_coordinator.resetear()


@pytest.fixture(autouse=True)
def reset_login_attempts():
    from app.composition import login_attempt_repository
    login_attempt_repository.resetear_todo()
    yield
    login_attempt_repository.resetear_todo()


@pytest.fixture(autouse=True)
def reset_rate_limit_middleware():
    from app.core import rls_middleware as rl
    rl.reset()
    yield
    rl.reset()


@pytest.fixture(autouse=True)
def reset_refresh_tokens():
    from app.db.models import RefreshTokenModel
    from app.db.session import get_session
    with get_session() as session:
        session.query(RefreshTokenModel).delete(synchronize_session=False)
    yield
    with get_session() as session:
        session.query(RefreshTokenModel).delete(synchronize_session=False)


@pytest.fixture(autouse=True)
def _seed_test_role_users_with_full_visibility():
    from app.db.models import (
        RoleAssignmentModel,
        SiteModel,
        UserModel,
    )
    from app.db.session import get_session
    from app.composition import user_repository

    _accounts = [
        ("admin", "admin123", True),
        ("operator", "operator123", False),
        ("observer", "observer123", False),
        ("super-admin", "superadmin123", True),
    ]
    for username, password, is_sys_admin in _accounts:
        if user_repository.obtener_por_username(username) is None:
            user_repository.crear(username, password, is_system_admin=is_sys_admin)

    with get_session() as session:
        all_site_ids = [
            r[0] for r in session.query(SiteModel.id).filter(
                SiteModel.kind == "REGULAR"
            ).all()
        ]
        for role in ("observer", "operator"):
            user_row = session.query(UserModel).filter_by(username=role).first()
            if user_row is None:
                continue
            session.query(RoleAssignmentModel).filter(
                RoleAssignmentModel.user_id == user_row.id,
                RoleAssignmentModel.device_group_id.is_(None),
                RoleAssignmentModel.site_id.in_(all_site_ids) if all_site_ids else False,
            ).delete(synchronize_session=False)
            for sid in all_site_ids:
                session.add(RoleAssignmentModel(
                    user_id=user_row.id,
                    site_id=sid,
                    device_group_id=None,
                    role=role,
                ))
    yield


@pytest.fixture(autouse=True)
def mock_ansible_service(monkeypatch):
    from app.services import ansible_service

    def _fake_run_playbook(playbook: str, extravars: dict, inventory: str | None = None, device: str | None = None, vendor: str | None = None) -> dict:
        dev = device or extravars.get("device", "")
        if dev == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure"}
        return {"rc": 0, "stdout": "Simulated playbook output", "stderr": ""}

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run_playbook)
