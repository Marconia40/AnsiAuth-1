from __future__ import annotations

from app.models.device import Device


def device_con_driver(driver, *, name: str = "swcs01", vendor: str = "cisco_ios") -> Device:
    d = Device(
        name=name, host="192.0.2.50", vendor=vendor,
        username="admin", encrypted_password="x",
        platform="ios" if vendor == "cisco_ios" else "vrp",
    )
    d._driver = driver
    d._password = "fake-password"
    return d
