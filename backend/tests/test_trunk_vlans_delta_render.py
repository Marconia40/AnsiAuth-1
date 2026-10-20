from __future__ import annotations

import re

import pytest

from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor


def _render(driver, variant_vars, *, alternativa: int | None = None):
    op_key, variant, vars = variant_vars
    entry = driver._cargar_comandos()[op_key][variant]
    paso = entry["primary"] if alternativa is None else entry["alternatives"][alternativa]
    return driver._renderizar_paso(paso, vars)


def _hw(add, remove, interface="GE0/0/43"):
    return HuaweiVendor().resolver_set_trunk_vlans_delta(interface, add, remove)


def test_huawei_add_solo_agrega_y_no_toca_el_resto():
    op_key, variant, _ = _hw([600], [])
    assert (op_key, variant) == ("set_trunk_vlans_delta", "add")
    extravars = _render(HuaweiVendor(), _hw([600], []))
    assert extravars["command_block"] == (
        "system-view\ninterface GE0/0/43\nport trunk allow-pass vlan 600\ncommit\nquit\nquit"
    )


def test_huawei_remove_solo_quita():
    assert _hw([], [144])[1] == "remove"
    extravars = _render(HuaweiVendor(), _hw([], [144]))
    assert extravars["command_block"] == (
        "system-view\ninterface GE0/0/43\nundo port trunk allow-pass vlan 144\ncommit\nquit\nquit"
    )


def test_huawei_both_agrega_primero_y_despues_quita():
    assert _hw([600], [144])[1] == "both"
    lineas = _render(HuaweiVendor(), _hw([600], [144]))["command_block"].split("\n")
    assert lineas.index("port trunk allow-pass vlan 600") < lineas.index("undo port trunk allow-pass vlan 144")


def test_huawei_nunca_emite_undo_all():
    for add, remove in (([600], []), ([], [144]), ([600], [144])):
        bloque = _render(HuaweiVendor(), _hw(add, remove))["command_block"]
        assert "undo port trunk allow-pass vlan all" not in bloque
        assert "vlan all" not in bloque


def test_huawei_rangos_contiguos_se_comprimen():
    bloque = _render(HuaweiVendor(), _hw([10, 11, 12, 20], []))["command_block"]
    assert "port trunk allow-pass vlan 10 to 12 20" in bloque.split("\n")


def test_huawei_parte_listas_largas_en_tandas_de_10_items():
    vlans = [10 + 2 * i for i in range(12)]
    lineas = _render(HuaweiVendor(), _hw(vlans, []))["command_block"].split("\n")
    allow = [l for l in lineas if l.startswith("port trunk allow-pass vlan")]
    assert len(allow) == 2
    assert len(allow[0].split()) == 4 + 10
    assert len(allow[1].split()) == 4 + 2
    emitidas = [int(x) for l in allow for x in l.split()[4:]]
    assert emitidas == vlans


def test_huawei_ambos_lados_vacios_es_error():
    with pytest.raises(ValueError):
        _hw([], [])


def test_huawei_alternativa_de_interfaz_usa_el_nombre_completo_y_no_undo_all():
    extravars = _render(HuaweiVendor(), _hw([600], [144]), alternativa=0)
    assert "interface GigabitEthernet0/0/43" in extravars["command_block"]
    assert "commit" not in extravars["command_block"].split("\n")
    assert "vlan all" not in extravars["command_block"]


def test_huawei_trigger_de_interfaz_matchea_el_error_real():
    entry = HuaweiVendor()._cargar_comandos()["set_trunk_vlans_delta"]["add"]
    error_real = (
        "[~swhw02]interface GE0/0/43\r\n"
        "                  ^\r\n"
        "Error: Wrong parameter found at '^' position.\r\n"
    )
    assert re.search(entry["alternatives"][0]["triggered_by_error"], error_real)


def test_huawei_las_3_variantes_tienen_las_2_alternativas():
    entradas = HuaweiVendor()._cargar_comandos()["set_trunk_vlans_delta"]
    for variant in ("add", "remove", "both"):
        assert len(entradas[variant]["alternatives"]) == 2


def _ci(add, remove, interface="Gi0/1"):
    return CiscoVendor().resolver_set_trunk_vlans_delta(interface, add, remove)


def test_cisco_add_usa_la_palabra_add():
    assert _ci([600, 601, 700], [])[1] == "add"
    extravars = _render(CiscoVendor(), _ci([600, 601, 700], []))
    assert extravars["parents"] == "interface Gi0/1"
    assert extravars["lines"] == ["switchport trunk allowed vlan add 600-601,700"]
    assert extravars["match"] == "none"


def test_cisco_remove_usa_la_palabra_remove():
    assert _ci([], [144])[1] == "remove"
    extravars = _render(CiscoVendor(), _ci([], [144]))
    assert extravars["lines"] == ["switchport trunk allowed vlan remove 144"]


def test_cisco_both_agrega_primero_y_despues_quita():
    assert _ci([600], [144])[1] == "both"
    extravars = _render(CiscoVendor(), _ci([600], [144]))
    assert extravars["lines"] == [
        "switchport trunk allowed vlan add 600",
        "switchport trunk allowed vlan remove 144",
    ]


def test_cisco_nunca_reemplaza_la_lista_completa():
    for add, remove in (([600], []), ([], [144]), ([600], [144])):
        lineas = _render(CiscoVendor(), _ci(add, remove))["lines"]
        for l in lineas:
            assert l.startswith("switchport trunk allowed vlan add ") or l.startswith(
                "switchport trunk allowed vlan remove "
            )


def test_cisco_ambos_lados_vacios_es_error():
    with pytest.raises(ValueError):
        _ci([], [])
