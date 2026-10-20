from __future__ import annotations

from app.composition import puerto_repository
from app.models.device import Device
from app.models.port import Puerto
from app.services import ansible_service
from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor

from tests._puerto_fakes import get_or_create_device

_HUAWEI_BRIEF = """\
Interface                   PHY     Protocol  InUti OutUti   inErrors  outErrors
GigabitEthernet0/0/1        up      up        0%    0%             0        0
"""
_HUAWEI_DESC = """\
Interface                  PHY      Protocol Description
GigabitEthernet0/0/1       up       up       cross-vendor-test
"""
_HUAWEI_PORTVLAN = """\
Port                    Link Type    PVID  Trunk VLAN List
-------------------------------------------------------------------
GigabitEthernet0/0/1    access       10    -
"""
_HUAWEI_STORM = ""

_CISCO_STATUS = """\
Port      Name               Status       Vlan       Duplex  Speed Type
Gi0/1     cross-vendor-test  connected    10         a-full  a-1000 10/100/1000BaseTX
"""
_CISCO_DESC = """\
Interface                      Status         Protocol Description
Gi0/1                          up             up       cross-vendor-test
"""
_CISCO_SW = """\
Name: Gi0/1
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Access Mode VLAN: 10 (TEST)
Trunking Native Mode VLAN: 1 (default)
Trunking VLANs Enabled: ALL
"""
_CISCO_STORM = ""
_CISCO_RUNNING_CONFIG = ""


def _fake_device(vendor: str) -> Device:
    dev = Device(
        name=f"{vendor}-driver-x", host="192.0.2.1", vendor=vendor,
        username="admin", encrypted_password="enc",
        platform="ios" if vendor == "cisco_ios" else "vrp",
    )
    dev._driver = CiscoVendor() if vendor == "cisco_ios" else HuaweiVendor()
    dev._password = "fake-password"
    return dev


def test_driver_level_parser_parity_across_vendors(monkeypatch):
    def _fake_run_playbook(playbook, extravars, inventory=None, device=None, vendor=None):
        if playbook == "vendors/huawei/run.yml":
            return {
                "rc": 0, "stdout": "", "stderr": "",
                "stdouts": [_HUAWEI_BRIEF, _HUAWEI_DESC, _HUAWEI_PORTVLAN, _HUAWEI_STORM],
            }
        if playbook == "vendors/cisco/run.yml":
            return {
                "rc": 0, "stdout": "", "stderr": "",
                "stdouts": [_CISCO_STATUS, _CISCO_DESC, _CISCO_SW, _CISCO_STORM, _CISCO_RUNNING_CONFIG],
            }
        raise AssertionError(f"unexpected playbook: {playbook}")

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run_playbook)

    huawei_dev = _fake_device("huawei_vrp")
    cisco_dev = _fake_device("cisco_ios")

    huawei_ports = huawei_dev.driver.list_ports(huawei_dev, huawei_dev.password)
    cisco_ports = cisco_dev.driver.list_ports(cisco_dev, cisco_dev.password)

    assert len(huawei_ports) == 1
    assert len(cisco_ports) == 1
    hp, cp = huawei_ports[0], cisco_ports[0]
    assert isinstance(hp, Puerto)
    assert isinstance(cp, Puerto)

    assert hp.description == "cross-vendor-test"
    assert cp.description == "cross-vendor-test"
    assert hp.mode == "access"
    assert cp.mode == "access"
    assert hp.access_vlan == 10
    assert cp.access_vlan == 10
    assert hp.admin_up is True
    assert cp.admin_up is True


def test_api_envelope_identical_for_both_vendors(client):
    huawei_dev = get_or_create_device("huawei-api-x", site_name="Multi Vendor Test Site", vendor="huawei_vrp")
    cisco_dev = get_or_create_device("cisco-api-x", site_name="Multi Vendor Test Site", vendor="cisco_ios")

    for dev in (huawei_dev, cisco_dev):
        puerto_repository.add(Puerto(
            interface="GigabitEthernet0/0/1", device=dev.name, description="cross-vendor-test",
            admin_up=True, operational_up=True, mode="access", access_vlan=10,
        ))

    huawei_resp = client.get(f"/api/v1/devices/{huawei_dev.name}/ports/")
    cisco_resp = client.get(f"/api/v1/devices/{cisco_dev.name}/ports/")

    assert huawei_resp.status_code == 200
    assert cisco_resp.status_code == 200

    huawei_body = huawei_resp.json()
    cisco_body = cisco_resp.json()
    assert set(huawei_body.keys()) == set(cisco_body.keys())
    assert huawei_body["success"] is True
    assert cisco_body["success"] is True

    huawei_payload = huawei_body["data"]["data"]
    cisco_payload = cisco_body["data"]["data"]
    assert set(huawei_payload.keys()) == set(cisco_payload.keys())

    assert set(huawei_payload["ports"][0].keys()) == set(cisco_payload["ports"][0].keys())
    assert huawei_payload["ports"][0]["description"] == cisco_payload["ports"][0]["description"]
