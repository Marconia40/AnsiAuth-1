from __future__ import annotations

from app.composition import plugin_registry
from app.models.device import Device
from app.services import secret_vault as secret_vault_module
from app.services.vendors.mock import MockVendor


def _make_device(**overrides) -> Device:
    defaults = dict(
        name="sw1", host="10.0.0.1", vendor="huawei_vrp",
        username="admin", encrypted_password="enc",
    )
    defaults.update(overrides)
    return Device(**defaults)


def test_registered_mock_vendor_resolves_as_device_driver(monkeypatch):
    mv = MockVendor()
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", mv)

    device = _make_device()
    assert device.driver is mv
    assert isinstance(device.driver, MockVendor)


def test_mock_vendor_list_ports_returns_data(monkeypatch):
    mv = MockVendor()
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", mv)

    device = _make_device()
    ports = device.driver.list_ports(device, "unused-password")
    assert len(ports) > 0


def test_driver_resolution_alone_never_touches_password(monkeypatch):
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", MockVendor())

    def _boom(*_a, **_kw):
        raise AssertionError("decrypt must not run just from accessing .driver")
    monkeypatch.setattr(secret_vault_module.vault, "decrypt", _boom)

    device = _make_device()
    _ = device.driver
    assert device._password is None


def test_password_is_decrypted_once_a_driver_call_actually_needs_it(monkeypatch):
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", MockVendor())

    calls = []

    def _fake_decrypt(enc):
        calls.append(enc)
        return "decrypted-pw"
    monkeypatch.setattr(secret_vault_module.vault, "decrypt", _fake_decrypt)

    device = _make_device()
    device.driver.list_ports(device, device.password)

    assert calls == ["enc"]
    assert device._password == "decrypted-pw"
