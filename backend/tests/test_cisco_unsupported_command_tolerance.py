from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import ansible_service
from app.services.vendors.cisco.driver import CiscoVendor


class _FakeDevice:
    name = "cisco-01"
    host = "192.0.2.10"
    username = "admin"
    auth_method = "password"
    vendor = "cisco_ios"


_STATUS = (
    "Port      Name               Status       Vlan       Duplex  Speed Type\n"
    "Gi0/1                        connected    10         a-full  a-1000 10/100/1000BaseTX\n"
)
_DESC = (
    "Interface                      Status         Protocol Description\n"
    "Gi0/1                          up             up       \n"
)
_SW = (
    "Name: Gi0/1\n"
    "Switchport: Enabled\n"
    "Administrative Mode: static access\n"
    "Operational Mode: static access\n"
    "Access Mode VLAN: 10 (MGMT)\n"
    "Trunking Native Mode VLAN: 1 (default)\n"
    "Trunking VLANs Enabled: ALL\n"
)
_STORM_INVALID = (
    "show storm-control broadcast\r\n"
    "show storm-control broadcast\r\n"
    " ^\r\n"
    "% Invalid input detected at '^' marker.\r\n\r\n"
    "cisco-01#"
)
_STORM_TABLE_WITHOUT_TARGET_PORT = (
    "Interface  Filter State     Trap State     Upper        Lower        Current\n"
    "--------- ---------------  -------------  -----------  -----------  ----------\n"
    "Gi0/2      inactive         inactive        100.00%      100.00%      0.00%\n"
)
_STORM_TABLE_LINK_DOWN = (
    "Key: U - Unicast, B - Broadcast, M - Multicast\n"
    "Interface  Filter State   Upper        Lower        Current     Action     Type\n"
    "---------  -------------  -----------  -----------  ----------  ---------  ----\n"
    "Gi0/1      Link Down           10.00%       10.00%       0.00%  Shut-Trap  B   \n"
)
_RUNNING_CONFIG_WITH_STORM = (
    "interface GigabitEthernet0/1\n"
    " switchport access vlan 258\n"
    " switchport mode access\n"
    " shutdown\n"
    " storm-control broadcast level 10.00\n"
    " storm-control multicast level 10.00\n"
    " storm-control action shutdown\n"
    " storm-control action trap\n"
)


def _make_run_result(rc: int, stdouts: list[str]) -> dict:
    return {"rc": rc, "stdout": "", "stderr": "", "stdouts": stdouts}


def test_list_ports_tolerates_unsupported_storm_control(monkeypatch):
    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(rc=1, stdouts=[_STATUS, _DESC, _SW, _STORM_INVALID])

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    ports = CiscoVendor().list_ports(_FakeDevice(), "pw")

    assert len(ports) == 1
    p = ports[0]
    assert p.interface == "Gi0/1"
    assert p.mode == "access"
    assert p.access_vlan == 10
    assert p.storm_control_enabled is None
    assert p.storm_control_threshold is None


def test_list_ports_storm_control_supported_but_not_configured_is_false(monkeypatch):
    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(
            rc=0, stdouts=[_STATUS, _DESC, _SW, _STORM_TABLE_WITHOUT_TARGET_PORT],
        )

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    ports = CiscoVendor().list_ports(_FakeDevice(), "pw")

    assert len(ports) == 1
    p = ports[0]
    assert p.interface == "Gi0/1"
    assert p.storm_control_enabled is False
    assert p.storm_control_threshold is None


def test_list_ports_storm_control_shutdown_port_uses_running_config(monkeypatch):
    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(
            rc=0,
            stdouts=[_STATUS, _DESC, _SW, _STORM_TABLE_LINK_DOWN, _RUNNING_CONFIG_WITH_STORM],
        )

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    ports = CiscoVendor().list_ports(_FakeDevice(), "pw")

    assert len(ports) == 1
    p = ports[0]
    assert p.interface == "Gi0/1"
    assert p.storm_control_enabled is True
    assert p.storm_control_threshold == 10.0
    assert p.storm_control_action == "shutdown"
    assert p.storm_control_trap is True


def test_list_ports_still_raises_when_device_unreachable(monkeypatch):
    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(rc=1, stdouts=[])

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    with pytest.raises(RuntimeError, match="cisco-01"):
        CiscoVendor().list_ports(_FakeDevice(), "pw")


def test_list_ports_still_raises_when_all_slots_empty_string(monkeypatch):
    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(rc=1, stdouts=[""] * 4)

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    with pytest.raises(RuntimeError, match="cisco-01"):
        CiscoVendor().list_ports(_FakeDevice(), "pw")


def test_read_core_state_tolerates_unsupported_storm_control(monkeypatch):
    v = CiscoVendor()
    cmds = v._cargar_comandos()
    n_vlan = len(cmds["list_vlans"]["primary"]["commands"])
    n_port = len(cmds["list_ports"]["primary"]["commands"])
    n_svi = len(cmds["get_svis"]["primary"]["commands"])

    vlan_brief = (
        "VLAN Name                             Status    Ports\n"
        "---- -------------------------------- --------- ------\n"
        "10   MGMT                             active    Gi0/1\n"
    )
    stub_stdouts = (
        [vlan_brief]
        + [_STATUS, _DESC, _SW, _STORM_INVALID] + [""] * (n_port - 4)
        + ["", ""]
    )
    assert len(stub_stdouts) == n_vlan + n_port + n_svi

    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(rc=1, stdouts=stub_stdouts)

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    vlans, ports, svis = v.read_core_state(_FakeDevice(), "pw")

    assert any(vl.vlan_id == 10 for vl in vlans)
    assert len(ports) == 1
    assert ports[0].storm_control_enabled is None


def test_extractor_handles_loop_results_with_list_or_str_stdout():
    from app.services.ansible_service import _extract_all_command_outputs

    class _Runner:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "results": [
                            {"stdout": ["cisco status output"]},
                            {"stdout": ["cisco desc output"]},
                            {"stdout": ["cisco switchport output"]},
                            {"failed": True, "msg": "% Invalid input"},
                            {"stdout": "huawei-style string stdout"},
                            {"stdout": []},
                            {},
                        ]
                    }
                },
            }
        ]

    outputs = _extract_all_command_outputs(_Runner())

    assert len(outputs) == 7
    assert outputs[0] == "cisco status output"
    assert outputs[1] == "cisco desc output"
    assert outputs[2] == "cisco switchport output"
    assert outputs[3] == ""
    assert outputs[4] == "huawei-style string stdout"
    assert outputs[5] == ""
    assert outputs[6] == ""


def test_leer_partial_ok_passes_tolerate_flag_to_playbook(monkeypatch):
    captured: list[dict] = []

    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        captured.append(dict(extravars))
        return _make_run_result(rc=0, stdouts=[""] * 4)

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    v = CiscoVendor()
    v._leer(["show foo"], _FakeDevice(), "pw")
    v._leer(["show bar"], _FakeDevice(), "pw", partial_ok=True)

    assert "tolerate_command_errors" not in captured[0]
    assert captured[1].get("tolerate_command_errors") is True


def test_leer_default_behavior_unchanged_on_failure(monkeypatch):
    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        return _make_run_result(rc=1, stdouts=["some partial output"])

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    v = CiscoVendor()
    with pytest.raises(RuntimeError, match="cisco-01"):
        v._leer(["show vlan brief"], _FakeDevice(), "pw")
