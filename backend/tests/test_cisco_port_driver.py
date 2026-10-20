import pytest

from app.models.device import Device
from app.models.port import Puerto
from app.services import ansible_service
from app.services.parsers.port_parser import CiscoPortParser
from app.services.vendors.cisco.driver import CiscoVendor


def _make_device() -> Device:
    dev = Device(
        name="cisco1", host="192.0.2.10", vendor="cisco_ios",
        username="admin", encrypted_password="encrypted", platform="ios",
    )
    dev._driver = CiscoVendor()
    dev._password = "pw"
    return dev


_STATUS = """\
Port      Name               Status       Vlan       Duplex  Speed Type
Gi0/1     web01              connected    10         a-full  a-1000 10/100/1000BaseTX
"""

_DESC = """\
Interface                      Status         Protocol Description
Gi0/1                          up             up       web-server-01
"""

_SW = """\
Name: Gi0/1
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Access Mode VLAN: 10 (WEB)
Trunking Native Mode VLAN: 1 (default)
Trunking VLANs Enabled: ALL
"""


def _run_ports(device):
    return device.driver.list_ports(device, device.password)


def test_list_ports_parses_five_command_response(monkeypatch):
    captured: dict = {}

    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        captured["playbook"] = playbook
        captured["extravars"] = extravars
        return {
            "rc": 0, "stdout": "", "stderr": "",
            "stdouts": [_STATUS, _DESC, _SW, "", ""],
        }

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)
    dev = _make_device()
    ports = _run_ports(dev)

    assert captured["playbook"] == "vendors/cisco/run.yml"
    assert captured["extravars"]["device"] == "cisco1"
    assert captured["extravars"]["tolerate_command_errors"] is True
    assert len(captured["extravars"]["commands"]) == 5

    assert len(ports) == 1
    p = ports[0]
    assert isinstance(p, Puerto)
    assert p.interface == "Gi0/1"
    assert p.description == "web-server-01"
    assert p.admin_up is True
    assert p.operational_up is True
    assert p.mode == "access"
    assert p.access_vlan == 10


def test_list_ports_handles_partial_stdouts(monkeypatch):
    monkeypatch.setattr(
        ansible_service, "run_playbook",
        lambda **kw: {"rc": 0, "stdout": "", "stderr": "", "stdouts": [_STATUS]},
    )
    ports = _run_ports(_make_device())
    assert ports == []


def test_list_ports_raises_runtime_error_on_non_zero_rc(monkeypatch):
    monkeypatch.setattr(
        ansible_service, "run_playbook",
        lambda **kw: {"rc": 1, "stdout": "", "stderr": "SSH timeout", "stdouts": []},
    )
    with pytest.raises(RuntimeError) as exc:
        _run_ports(_make_device())
    assert "SSH timeout" in str(exc.value)
    assert "cisco1" in str(exc.value)


def test_list_ports_raises_when_stdouts_missing(monkeypatch):
    monkeypatch.setattr(
        ansible_service, "run_playbook",
        lambda **kw: {"rc": 0, "stdout": "", "stderr": "", "stdouts": []},
    )
    with pytest.raises(RuntimeError) as exc:
        _run_ports(_make_device())
    assert "no command output" in str(exc.value).lower()


def test_list_ports_wraps_parser_errors(monkeypatch):
    monkeypatch.setattr(
        ansible_service, "run_playbook",
        lambda **kw: {"rc": 0, "stdout": "", "stderr": "", "stdouts": [_STATUS, _DESC, _SW, "", ""]},
    )

    def _boom(*args, **kwargs):
        raise ValueError("simulated parser failure")

    monkeypatch.setattr(CiscoPortParser, "parse_ports", classmethod(lambda cls, *a, **k: _boom()))

    with pytest.raises(RuntimeError) as exc:
        _run_ports(_make_device())
    assert "simulated parser failure" in str(exc.value)
    assert "cisco1" in str(exc.value)
