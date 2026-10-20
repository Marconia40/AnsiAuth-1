from __future__ import annotations

import pytest

from app.models.port import Puerto


def test_description_only_valid():
    Puerto(interface="Gi0/1", description="UPLINK").validar()


def test_clear_description_valid():
    p = Puerto(interface="Gi0/1", description="")
    p.validar()
    assert "description" in p.mutation_fields


def test_admin_up_true_valid():
    p = Puerto(interface="Gi0/1", admin_up=True)
    p.validar()
    assert "admin_up" in p.mutation_fields


def test_admin_up_false_valid():
    p = Puerto(interface="Gi0/1", admin_up=False)
    p.validar()
    assert "admin_up" in p.mutation_fields


def test_access_mode_with_vlan_valid():
    p = Puerto(interface="Gi0/1", mode="access", access_vlan=20)
    p.validar()
    assert p.mode == "access"
    assert p.access_vlan == 20


def test_trunk_mode_with_both_vlan_dimensions_valid():
    p = Puerto(interface="Gi0/1", mode="trunk", access_vlan=1, allowed_vlans=[10, 20, 30])
    p.validar()
    assert p.mode == "trunk"
    assert p.allowed_vlans == [10, 20, 30]


def test_trunk_mode_with_only_access_vlan_now_raises():
    p = Puerto(interface="Gi0/1", mode="trunk", access_vlan=10)
    with pytest.raises(ValueError, match="allowed_vlans"):
        p.validar()


def test_access_vlan_is_dual_purpose_pvid_on_trunk():
    p = Puerto(interface="Gi0/1", mode="trunk", access_vlan=10, allowed_vlans=[10, 20])
    p.validar()
    assert p.access_vlan == 10


def test_no_mode_no_cross_field_rule_applies():
    p = Puerto(interface="Gi0/1", description="X")
    p.validar()


def test_empty_interface_raises():
    with pytest.raises(ValueError):
        Puerto(interface="", description="X")


def test_no_mutation_fields_raises():
    with pytest.raises(ValueError, match="at least one mutation field"):
        Puerto(interface="Gi0/1").validar()


def test_access_vlan_without_mode_no_longer_raises():
    Puerto(interface="Gi0/1", access_vlan=10).validar()


def test_allowed_vlans_without_mode_no_longer_raises():
    Puerto(interface="Gi0/1", allowed_vlans=[10, 20]).validar()


def test_access_mode_with_allowed_vlans_raises():
    with pytest.raises(ValueError, match="access_vlan"):
        Puerto(interface="Gi0/1", mode="access", allowed_vlans=[10, 20]).validar()


def test_reserved_access_vlan_rejected():
    with pytest.raises(ValueError, match="reserved"):
        Puerto(interface="Gi0/1", mode="access", access_vlan=1003).validar()


def test_reserved_trunk_vlan_rejected():
    with pytest.raises(ValueError, match="reserved"):
        Puerto(interface="Gi0/1", allowed_vlans=[1003]).validar()


def test_vlan_out_of_range_rejected():
    with pytest.raises(ValueError, match="out of range"):
        Puerto(interface="Gi0/1", mode="access", access_vlan=4095).validar()


def test_overlength_description_rejected():
    with pytest.raises(ValueError):
        Puerto(interface="Gi0/1", description="x" * 201).validar()


def test_description_control_chars_rejected():
    with pytest.raises(ValueError):
        Puerto(interface="Gi0/1", description="with\nnewline").validar()


class _FakeDriver:
    def resolver_set_access_mode(self, interface, vlan_id, *, viene_de_trunk_con_vlans=True):
        return ("set_access_mode", None, {"interface": interface, "vlan_id": vlan_id})

    def aplicar_paso(self, op_key, variant, vars, device, password):
        return {"rc": 0, "success": True}


class _FakeDevice:
    driver = _FakeDriver()
    password = "pw"


def test_aplicar_rejects_arbitrary_multi_field_combo():
    p = Puerto(
        interface="GigabitEthernet1/0/1", description="DESK", admin_up=True,
        mode="access", access_vlan=10,
    )
    p.validar()
    result = p.aplicar(_FakeDevice())
    assert result["accion"] == "configurar_modo_access"


def test_aplicar_rejects_two_single_fields_without_mode():
    p = Puerto(interface="Gi0/1", description="DESK", admin_up=True)
    p.validar()
    with pytest.raises(ValueError):
        p.aplicar(_FakeDevice())
