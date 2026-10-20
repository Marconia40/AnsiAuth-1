from __future__ import annotations

import pytest

from app.services import ssh_direct_service
from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor


class _NullAgentCtx:
    def __enter__(self):
        return {}

    def __exit__(self, *a):
        return False


class _FakeKeyDevice:
    name = "cisco-01"
    host = "192.0.2.10"
    username = "admin"
    vendor = "cisco_ios"
    auth_method = "key"


def _fake_run_factory(transcript: str):
    def _fake_run(cmd, input, capture_output, text, timeout, env):
        class _Proc:
            returncode = 0
            stdout = transcript
            stderr = ""
        return _Proc()
    return _fake_run


def _patch_ssh_paced(monkeypatch, fake_run):
    monkeypatch.setattr(ssh_direct_service, "_SSH_DRAIN_DELAY_S", 0)

    def _run_ssh_paced(cmd, lines, env, terminador="quit"):
        return fake_run(cmd, "\n".join(lines) + f"\n{terminador}\n", True, True, None, env)

    monkeypatch.setattr(ssh_direct_service, "_run_ssh_paced", _run_ssh_paced)


def test_cisco_list_ports_tolerates_unsupported_storm_control_via_ssh_direct(monkeypatch):
    transcript = (
        "cisco-01#terminal length 0\n"
        "cisco-01#terminal width 0\n"
        "cisco-01#show interfaces status\n"
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi0/1                        connected    10         a-full  a-1000 10/100/1000BaseTX\n"
        "cisco-01#show interfaces description\n"
        "Interface                      Status         Protocol Description\n"
        "Gi0/1                          up             up       \n"
        "cisco-01#show interfaces switchport\n"
        "Name: Gi0/1\n"
        "Switchport: Enabled\n"
        "Administrative Mode: static access\n"
        "Operational Mode: static access\n"
        "Access Mode VLAN: 10 (MGMT)\n"
        "Trunking Native Mode VLAN: 1 (default)\n"
        "Trunking VLANs Enabled: ALL\n"
        "cisco-01#show storm-control broadcast\n"
        " ^\n"
        "% Invalid input detected at '^' marker.\n"
        "\n"
        "cisco-01#show running-config | section ^interface\n"
        "interface GigabitEthernet0/1\n"
        " switchport access vlan 10\n"
        " switchport mode access\n"
        "cisco-01#exit"
    )
    _patch_ssh_paced(monkeypatch, _fake_run_factory(transcript))
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    ports = CiscoVendor().list_ports(_FakeKeyDevice(), "pw")

    assert len(ports) == 1
    p = ports[0]
    assert p.interface == "Gi0/1"
    assert p.mode == "access"
    assert p.access_vlan == 10
    assert p.storm_control_enabled is None
    assert p.storm_control_threshold is None


class _FakeKeyDeviceHuawei(_FakeKeyDevice):
    name = "huawei-01"
    vendor = "huawei_vrp"


def test_huawei_list_ports_parses_correctly_via_single_fused_ssh_session(monkeypatch):
    transcript = (
        "<huawei-01>screen-length 0 temporary\n"
        "<huawei-01>display interface brief\n"
        "Interface                   PHY     Protocol  InUti OutUti   inErrors  outErrors\n"
        "GigabitEthernet0/0/1        up      up        0.01%  0.01%        0        0\n"
        "<huawei-01>display interface description\n"
        "Interface                  PHY      Protocol Description\n"
        "GigabitEthernet0/0/1       up       up       Workstation01\n"
        "<huawei-01>display port vlan\n"
        "Port                    Link Type    PVID  Trunk VLAN List\n"
        "GigabitEthernet0/0/1    access       10    -\n"
        "<huawei-01>display current-configuration interface\n"
        "<huawei-01>quit"
    )
    _patch_ssh_paced(monkeypatch, _fake_run_factory(transcript))
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    ports = HuaweiVendor().list_ports(_FakeKeyDeviceHuawei(), "pw")

    assert len(ports) == 1
    p = ports[0]
    assert p.interface == "GE0/0/1"
    assert p.description == "Workstation01"
    assert p.mode == "access"
    assert p.access_vlan == 10
    assert p.admin_up is True
    assert p.operational_up is True


def test_cisco_list_ports_raises_when_session_truncated_mid_batch(monkeypatch):
    transcript = (
        "cisco-01#terminal length 0\n"
        "cisco-01#terminal width 0\n"
        "cisco-01#show interfaces status\n"
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi0/1                        connected    10         a-full  a-1000 10/100/1000BaseTX\n"
        "cisco-01#show interfaces description\n"
        "Interface                      Status         Protocol Description\n"
        "Gi0/1                          up             up       \n"
        "cisco-01#show interfaces switchport\n"
        "Name: Gi0/1\n"
        "Switchport: Enabled\n"
        "Administrative Mode: static access\n"
        "Operational Mode: static access\n"
        "Access Mode VLAN: 10 (MGMT)\n"
        "Trunking Native Mode VLAN: 1 (default)\n"
        "Trunking VLANs Enabled: ALL\n"
        "cisco-01#"
    )
    _patch_ssh_paced(monkeypatch, _fake_run_factory(transcript))
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    with pytest.raises(RuntimeError, match="cisco-01"):
        CiscoVendor().list_ports(_FakeKeyDevice(), "pw")
