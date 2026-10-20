import pytest

from app.db.models import AuditLogModel, DeviceModel
from app.db.session import get_session


_TEST_DEVICE_NAMES = ("switch1", "sw2")


@pytest.fixture(autouse=True)
def reset_devices():
    def _clear():
        with get_session() as session:
            session.query(DeviceModel).filter(
                DeviceModel.name.in_(_TEST_DEVICE_NAMES)
            ).delete(synchronize_session=False)

    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True)
def _force_mock_vendor_drivers(monkeypatch):
    from app.composition import plugin_registry
    from app.services.vendors.mock import MockVendor

    mock = MockVendor()
    for vendor in ("cisco_ios", "huawei_vrp"):
        monkeypatch.setitem(plugin_registry._vendors, vendor, mock)


def _clear_audit_log():
    with get_session() as session:
        session.query(AuditLogModel).delete(synchronize_session=False)


_PAYLOAD = {
    "name": "switch1",
    "host": "192.168.1.10",
    "vendor": "cisco_ios",
    "username": "admin",
    "password": "admin",
    "site_id": 1,
}


def test_create_device(admin_client):
    response = admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "switch1"
    assert data["data"]["host"] == "192.168.1.10"
    assert "password" not in data["data"]
    assert "encrypted_password" not in data["data"]


def test_create_device_no_plaintext_password(admin_client):
    response = admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    body = response.text
    assert "admin" not in body or '"username": "admin"' not in body or "password" not in body
    assert "encrypted_password" not in body
    assert response.json()["data"].get("password") is None


def test_get_devices(admin_client):
    response = admin_client.get("/api/v1/devices/")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)
    for device in data["data"]:
        assert "password" not in device
        assert "encrypted_password" not in device


def test_get_device_by_name(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    response = admin_client.get("/api/v1/devices/switch1")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["name"] == "switch1"
    assert "password" not in data["data"]


def test_get_device_not_found(admin_client):
    response = admin_client.get("/api/v1/devices/nonexistent")
    assert response.status_code == 404


def test_delete_device(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    response = admin_client.delete("/api/v1/devices/switch1")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "switch1"


def test_delete_device_not_found(admin_client):
    response = admin_client.delete("/api/v1/devices/nonexistent")
    assert response.status_code == 403
    assert "nonexistent" in response.text


def test_observer_cannot_create_device(observer_client):
    response = observer_client.post("/api/v1/devices/", json=_PAYLOAD)
    assert response.status_code == 403


def test_create_vlan_with_registered_device(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    payload = {"vlan_id": 50, "name": "PROD", "devices": ["switch1"]}
    response = admin_client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 202
    assert response.json()["data"]["jobs"][0]["status"] in ("pending", "running", "completed")


def test_create_vlan_device_not_registered(admin_client):
    payload = {"vlan_id": 50, "name": "PROD", "devices": ["unknown_switch"]}
    response = admin_client.post("/api/v1/vlans/", json=payload)
    assert response.status_code == 404
    assert "unknown_switch" in response.text


def test_device_creation_is_audited(admin_client):
    _clear_audit_log()
    admin_client.post("/api/v1/devices/", json={**_PAYLOAD, "name": "sw2"})
    log = admin_client.get("/api/v1/audit/").json()["data"]["items"]
    entry = next(e for e in log if e["action"] == "device_registrado")
    assert entry["resource"] == "device"
    assert entry["device"] == "sw2"
    _clear_audit_log()


def test_password_encryption(admin_client):
    from app.composition import device_repository, secret_vault

    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    device = device_repository.get("switch1")
    assert device is not None
    assert device.encrypted_password != "admin"
    assert secret_vault.decrypt(device.encrypted_password) == "admin"


_CLAVE_HOST = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def _sembrar_clave(host):
    from app.services import known_hosts

    with open(known_hosts.KNOWN_HOSTS_ANSIBLE, "w") as f:
        f.write(f"{host} ssh-ed25519 {_CLAVE_HOST}\n")


def _clave_guardada(host):
    from app.services import known_hosts

    with open(known_hosts.KNOWN_HOSTS_ANSIBLE) as f:
        return f"{host} " in f.read()


def test_forget_host_key(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    _sembrar_clave(_PAYLOAD["host"])

    response = admin_client.post("/api/v1/devices/switch1/forget-host-key")
    assert response.status_code == 200
    assert response.json()["data"]["had_stored_key"] is True
    assert not _clave_guardada(_PAYLOAD["host"])

    again = admin_client.post("/api/v1/devices/switch1/forget-host-key")
    assert again.json()["data"]["had_stored_key"] is False

    with get_session() as session:
        assert session.query(AuditLogModel).filter_by(action="forget_host_key").count() >= 2


def test_forget_host_key_requires_admin(operator_client, admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    response = operator_client.post("/api/v1/devices/switch1/forget-host-key")
    assert response.status_code == 403


def test_host_change_forgets_old_host_key(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    _sembrar_clave(_PAYLOAD["host"])

    admin_client.put("/api/v1/devices/switch1", json={"host": "192.168.1.99"})
    assert not _clave_guardada(_PAYLOAD["host"])


def test_update_without_host_change_keeps_host_key(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    _sembrar_clave(_PAYLOAD["host"])

    admin_client.put("/api/v1/devices/switch1", json={"username": "netops"})
    assert _clave_guardada(_PAYLOAD["host"])


def test_delete_device_forgets_host_key(admin_client):
    admin_client.post("/api/v1/devices/", json=_PAYLOAD)
    _sembrar_clave(_PAYLOAD["host"])

    admin_client.delete("/api/v1/devices/switch1")
    assert not _clave_guardada(_PAYLOAD["host"])
