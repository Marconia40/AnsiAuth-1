from __future__ import annotations

from app.models.port import Puerto, _viene_de_trunk_con_vlans
from app.services.vendors.huawei.driver import HuaweiVendor
from app.services.vendors.cisco.driver import CiscoVendor


class _FakeDevice:
    name = "stub"
    vendor = "huawei_vrp"
    password = "pw"
    driver = HuaweiVendor()


def test_sin_pre_state_es_conservador():
    assert _viene_de_trunk_con_vlans(None) is True


def test_trunk_con_vlans_da_true():
    anterior = Puerto(interface="GE1/0/2", mode="trunk", allowed_vlans=[10, 20])
    assert _viene_de_trunk_con_vlans(anterior) is True


def test_trunk_sin_vlans_da_false():
    anterior = Puerto(interface="GE1/0/2", mode="trunk", allowed_vlans=[])
    assert _viene_de_trunk_con_vlans(anterior) is False


def test_access_da_false():
    anterior = Puerto(interface="GE1/0/2", mode="access", access_vlan=10)
    assert _viene_de_trunk_con_vlans(anterior) is False


def test_huawei_resolver_con_confirmacion_por_default():
    op_key, variant, vars = HuaweiVendor().resolver_set_access_mode("GE1/0/2", 10)
    assert op_key == "set_access_mode"
    assert variant == "con_confirmacion"


def test_huawei_resolver_sin_confirmacion_explicito():
    op_key, variant, vars = HuaweiVendor().resolver_set_access_mode(
        "GE1/0/2", 10, viene_de_trunk_con_vlans=False,
    )
    assert variant == "sin_confirmacion"


def test_huawei_commands_yaml_tiene_las_2_variants_sin_la_y_en_una():
    comandos = HuaweiVendor()._cargar_comandos()["set_access_mode"]
    con = comandos["con_confirmacion"]["primary"]["block"]
    sin = comandos["sin_confirmacion"]["primary"]["block"]
    assert "y" in con
    assert "y" not in sin
    assert [l for l in con if l != "y"] == sin


def test_con_confirmacion_tiene_alternativa_sin_y_para_warning_no_interactivo():
    comandos = HuaweiVendor()._cargar_comandos()["set_access_mode"]["con_confirmacion"]
    alternativas = comandos["alternatives"]
    triggers = [a["triggered_by_error"] for a in alternativas]
    assert any("Unrecognized command" in t and r"\]y" in t for t in triggers)
    alt = next(a for a in alternativas if r"\]y" in a["triggered_by_error"])
    assert "y" not in alt["block"]


def test_regex_alternativa_matchea_el_error_real_observado():
    import re
    comandos = HuaweiVendor()._cargar_comandos()["set_access_mode"]["con_confirmacion"]
    alt = next(a for a in comandos["alternatives"] if r"\]y" in a["triggered_by_error"])
    error_real = (
        "I-GE1/0/2]port link-type access\r\n"
        "Warning: If this command is executed successfully, VLANs allowed "
        "to pass through this interface will be deleted.\r\n"
        "[*HUAWEI-GE1/0/2]y\r\n"
        "                 ^\r\n"
        "Error: Unrecognized command found at '^' position.\r\n"
        "[*HUAWEI-GE1/0/2]"
    )
    assert re.search(alt["triggered_by_error"], error_real)


def test_cisco_resolver_ignora_el_kwarg():
    op_key, variant, vars = CiscoVendor().resolver_set_access_mode(
        "Gi1/0/2", 10, viene_de_trunk_con_vlans=False,
    )
    assert variant is None


def test_resolver_paso_puerto_ya_en_access_no_pide_confirmacion():
    puerto = Puerto(interface="GE1/0/2", mode="access", access_vlan=20)
    actual = Puerto(interface="GE1/0/2", mode="access", access_vlan=10)
    op_key, variant, vars = puerto.resolver_paso(_FakeDevice(), actual)
    assert variant == "sin_confirmacion"


def test_resolver_paso_puerto_en_trunk_con_vlans_pide_confirmacion():
    puerto = Puerto(interface="GE1/0/2", mode="access", access_vlan=20)
    actual = Puerto(interface="GE1/0/2", mode="trunk", allowed_vlans=[10, 30])
    op_key, variant, vars = puerto.resolver_paso(_FakeDevice(), actual)
    assert variant == "con_confirmacion"


def test_resolver_paso_sin_actual_es_conservador():
    puerto = Puerto(interface="GE1/0/2", mode="access", access_vlan=20)
    op_key, variant, vars = puerto.resolver_paso(_FakeDevice(), None)
    assert variant == "con_confirmacion"
