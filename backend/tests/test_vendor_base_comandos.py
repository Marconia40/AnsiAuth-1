from __future__ import annotations

from app.services.vendors.base import VendorDriver, _comandos_desde_extravars


class _StubDriver(VendorDriver):
    _PLAYBOOK = "stub.yml"
    _NETWORK_OS = "stub"

    def create_vlan(self, *a, **kw): return {}
    def delete_vlan(self, *a, **kw): return {}
    def update_vlan(self, *a, **kw): return {}
    def save_config(self, *a, **kw): return {}
    def get_vlans(self, device, password): return []
    def list_ports(self, device, password): return []


class _FakeDevice:
    name = "stub-device"


def test_lines_con_parents():
    extravars = {"lines": ["switchport access vlan 20"], "parents": "interface Gi1/0/2"}
    assert _comandos_desde_extravars(extravars) == [
        "interface Gi1/0/2", "switchport access vlan 20",
    ]


def test_lines_sin_parents():
    extravars = {"lines": ["hostname sw1"]}
    assert _comandos_desde_extravars(extravars) == ["hostname sw1"]


def test_command_block_huawei():
    extravars = {"command_block": "system-view\ninterface Eth-Trunk1\ncommit\nquit\nquit"}
    assert _comandos_desde_extravars(extravars) == [
        "system-view", "interface Eth-Trunk1", "commit", "quit", "quit",
    ]


def test_commands_bare_exec():
    extravars = {"commands": ["write memory"]}
    assert _comandos_desde_extravars(extravars) == ["write memory"]


def test_command_blocks_lote_huawei():
    extravars = {"command_blocks": ["system-view\nquit", "interface Eth-Trunk2\ncommit\nquit"]}
    assert _comandos_desde_extravars(extravars) == [
        "system-view", "quit", "interface Eth-Trunk2", "commit", "quit",
    ]


def test_config_steps_lote_cisco():
    extravars = {"config_steps": [
        {"parents": "interface Gi1/0/1", "lines": ["switchport access vlan 10"]},
        {"lines": ["hostname sw1"]},
    ]}
    assert _comandos_desde_extravars(extravars) == [
        "interface Gi1/0/1", "switchport access vlan 10", "hostname sw1",
    ]


def test_shape_desconocida_da_vacio():
    assert _comandos_desde_extravars({}) == []
    assert _comandos_desde_extravars({"match": "line"}) == []


def test_aplicar_agrega_commands_shape_cisco(monkeypatch):
    driver = _StubDriver()
    monkeypatch.setattr(
        driver, "_ejecutar",
        lambda extravars, device, password: {"rc": 0, "stdout": "", "stderr": ""},
    )
    resultado = driver._aplicar(
        {"lines": ["switchport access vlan 20"], "parents": "interface Gi1/0/2"},
        _FakeDevice(), "pw", op_label="test",
    )
    assert resultado["success"] is True
    assert resultado["commands"] == ["interface Gi1/0/2", "switchport access vlan 20"]


def test_aplicar_agrega_commands_shape_huawei(monkeypatch):
    driver = _StubDriver()
    monkeypatch.setattr(
        driver, "_ejecutar",
        lambda extravars, device, password: {"rc": 0, "stdout": "[swhw01]...", "stderr": ""},
    )
    resultado = driver._aplicar(
        {"command_block": "system-view\ninterface Eth-Trunk1\ncommit\nquit\nquit"},
        _FakeDevice(), "pw", op_label="test",
    )
    assert resultado["success"] is True
    assert resultado["commands"] == [
        "system-view", "interface Eth-Trunk1", "commit", "quit", "quit",
    ]


def test_aplicar_sin_commands_cuando_shape_no_reconocida(monkeypatch):
    driver = _StubDriver()
    monkeypatch.setattr(
        driver, "_ejecutar",
        lambda extravars, device, password: {"rc": 0, "stdout": "", "stderr": ""},
    )
    resultado = driver._aplicar({}, _FakeDevice(), "pw", op_label="test")
    assert "commands" not in resultado


def test_aplicar_agrega_commands_tambien_en_fallo(monkeypatch):
    driver = _StubDriver()
    monkeypatch.setattr(
        driver, "_ejecutar",
        lambda extravars, device, password: {"rc": 1, "stdout": "", "stderr": "% Invalid input"},
    )
    resultado = driver._aplicar(
        {"lines": ["switchport access vlan 9999"], "parents": "interface Gi1/0/1"},
        _FakeDevice(), "pw", op_label="test",
    )
    assert resultado["success"] is False
    assert resultado["commands"] == ["interface Gi1/0/1", "switchport access vlan 9999"]
