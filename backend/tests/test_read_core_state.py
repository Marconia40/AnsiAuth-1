from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor


class _FakeDevice:
    name = "test-device"


def _stub_vlan_brief_cisco() -> str:
    return (
        "VLAN Name                             Status    Ports\n"
        "---- -------------------------------- --------- ------\n"
        "10   MGMT                             active    Gi1/0/1\n"
    )


def _stub_vlan_display_huawei() -> str:
    return (
        "The total number of vlans is : 1\n"
        "--------------------------------------------------------------------------------\n"
        "VID  Type     Ports\n"
        "--------------------------------------------------------------------------------\n"
        "10   common   UT:GE0/0/1(U)\n"
    )


def _stub_ports_cisco_status() -> str:
    return (
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi1/0/1                      connected    10         a-full  a-1000 10/100/1000BaseTX\n"
    )


def test_cisco_read_core_state_uses_a_single_leer_call():
    v = CiscoVendor()
    cmds = v._cargar_comandos()
    n_vlan = len(cmds["list_vlans"]["primary"]["commands"])
    n_port = len(cmds["list_ports"]["primary"]["commands"])
    svi_cmds = [c for c in cmds["get_svis"]["primary"]["commands"] if not c.startswith("show running-config")]
    n_svi = len(svi_cmds)
    expected_total = n_vlan + n_port + n_svi

    stub_stdouts = (
        [_stub_vlan_brief_cisco()]
        + [_stub_ports_cisco_status()] + [""] * (n_port - 1)
        + [""]
    )
    assert len(stub_stdouts) == expected_total, (
        "test fixture is out of sync with commands.yaml"
    )

    leer_mock = MagicMock(return_value=stub_stdouts)
    v._leer = leer_mock

    vlans, ports, svis = v.read_core_state(_FakeDevice(), "pw")

    assert leer_mock.call_count == 1
    (commands_arg,), _kwargs = leer_mock.call_args[:1], leer_mock.call_args[1]
    passed_commands = leer_mock.call_args.args[0]
    assert len(passed_commands) == expected_total
    assert passed_commands[:n_vlan] == cmds["list_vlans"]["primary"]["commands"]
    assert passed_commands[n_vlan:n_vlan + n_port] == cmds["list_ports"]["primary"]["commands"]
    assert passed_commands[n_vlan + n_port:] == svi_cmds
    assert sum(c.startswith("show running-config") for c in passed_commands) == 1

    assert any(v.vlan_id == 10 for v in vlans)


def test_cisco_read_core_state_wraps_port_parser_errors():
    v = CiscoVendor()
    stub_stdouts = [
        _stub_vlan_brief_cisco(),
        "GARBAGE\nBAD STATUS OUTPUT\n",
        "", "", "", "",
        "",
    ]
    v._leer = MagicMock(return_value=stub_stdouts)

    try:
        v.read_core_state(_FakeDevice(), "pw")
    except RuntimeError as exc:
        assert _FakeDevice.name in str(exc)


def test_huawei_read_core_state_no_vlanif_uses_two_leer_calls():
    v = HuaweiVendor()
    cmds = v._cargar_comandos()
    n_vlan = len(cmds["list_vlans"]["primary"]["commands"])
    n_port = len(cmds["list_ports"]["primary"]["commands"])

    session_a_stdouts = (
        [_stub_vlan_display_huawei()]
        + ["", "", "", ""]
        + ["Interface                         IP Address/Mask\nGigabitEthernet0/0/1              10.0.0.1/24\n"]
    )
    session_b_stdouts = [""]
    leer_mock = MagicMock(side_effect=[session_a_stdouts, session_b_stdouts])
    v._leer = leer_mock

    vlans, ports, svis = v.read_core_state(_FakeDevice(), "pw")

    assert leer_mock.call_count == 2

    session_a_cmds = leer_mock.call_args_list[0].args[0]
    assert len(session_a_cmds) == n_vlan + n_port + 1
    assert session_a_cmds[-1] == "display ip interface brief"

    session_b_cmds = leer_mock.call_args_list[1].args[0]
    assert session_b_cmds == ["display current-configuration configuration dhcp"]

    assert svis == []


def test_huawei_read_core_state_with_vlanif_uses_two_leer_calls():
    v = HuaweiVendor()

    session_a_stdouts = (
        [_stub_vlan_display_huawei()]
        + ["", "", "", ""]
        + [
            "Interface                         IP Address/Mask\n"
            "Vlanif10                          10.10.10.1/24\n"
            "Vlanif20                          10.10.20.1/24\n"
        ]
    )
    session_b_stdouts = ["", "", ""]
    leer_mock = MagicMock(side_effect=[session_a_stdouts, session_b_stdouts])
    v._leer = leer_mock

    v.read_core_state(_FakeDevice(), "pw")

    assert leer_mock.call_count == 2
    session_b_cmds = leer_mock.call_args_list[1].args[0]
    assert len(session_b_cmds) == 3
    assert session_b_cmds[0].startswith("display current-configuration interface Vlanif")
    assert session_b_cmds[-1] == "display current-configuration configuration dhcp"


def test_base_default_read_core_state_uses_individual_methods():
    from app.services.vendors.base import VendorDriver

    class _StubDriver(VendorDriver):
        _PLAYBOOK = "stub.yml"
        _NETWORK_OS = "stub"

        def create_vlan(self, *a, **kw): return {}
        def delete_vlan(self, *a, **kw): return {}
        def update_vlan(self, *a, **kw): return {}
        def save_config(self, *a, **kw): return {}
        def get_vlans(self, device, password): return ["v"]
        def list_ports(self, device, password): return ["p"]
        def get_svis(self, device, password): return ["s"]

    d = _StubDriver()
    vlans, ports, svis = d.read_core_state(_FakeDevice(), "pw")
    assert vlans == ["v"] and ports == ["p"] and svis == ["s"]


def test_cisco_read_core_state_toma_las_svi_de_la_running_config_de_los_puertos():
    v = CiscoVendor()
    cmds = v._cargar_comandos()
    n_vlan = len(cmds["list_vlans"]["primary"]["commands"])
    n_port = len(cmds["list_ports"]["primary"]["commands"])
    running = (
        "interface Vlan10\n"
        " description oficinas\n"
        " ip address 10.0.10.1 255.255.255.0\n"
        " ip helper-address 10.0.0.5\n"
        "interface GigabitEthernet1/0/1\n"
        " description uplink\n"
        " shutdown\n"
        "interface Vlan20\n"
        " ip address 10.0.20.1 255.255.255.0\n"
        "interface GigabitEthernet1/0/2\n"
        " shutdown\n"
    )
    brief = (
        "Vlan10                 10.0.10.1       YES NVRAM  up                    up\n"
        "Vlan20                 10.0.20.1       YES NVRAM  up                    up\n"
    )
    port_out = [_stub_ports_cisco_status()] + [""] * (n_port - 1)
    port_out[4] = running
    v._leer = MagicMock(return_value=[_stub_vlan_brief_cisco()] + port_out + [brief])

    _vlans, _ports, svis = v.read_core_state(_FakeDevice(), "pw")

    por_id = {s.vlan_id: s for s in svis}
    assert set(por_id) == {10, 20}
    assert por_id[10].description == "oficinas"
    assert por_id[10].ipv4_address == "10.0.10.1/24"
    assert por_id[10].dhcp_relay_servers == ["10.0.0.5"]
    assert por_id[10].admin_up is True
    assert por_id[20].admin_up is True
