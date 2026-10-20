from __future__ import annotations

import re

import pytest

from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor


def _render(driver, paso, *, alternativa: int | None = None):
    op_key, variant, vars = paso
    entry = driver._cargar_comandos()[op_key]
    entry = entry if variant is None else entry[variant]
    step = entry["primary"] if alternativa is None else entry["alternatives"][alternativa]
    return driver._renderizar_paso(step, vars)


def _hw(pvid, add, remove, interface="GE0/0/24"):
    return HuaweiVendor().resolver_set_trunk_config_delta(interface, pvid, add, remove)


def _hw_lineas(pvid, add, remove):
    bloque = _render(HuaweiVendor(), _hw(pvid, add, remove))["command_block"]
    return bloque.split("\n")


def test_huawei_los_tres_juntos_en_orden_add_pvid_remove():
    lineas = _hw_lineas(531, [600], [144])
    assert lineas == [
        "system-view", "interface GE0/0/24",
        "port trunk allow-pass vlan 600",
        "port trunk pvid vlan 531",
        "undo port trunk allow-pass vlan 144",
        "commit", "quit", "quit",
    ]


def test_huawei_solo_pvid_no_deja_lineas_en_blanco():
    lineas = _hw_lineas(531, [], [])
    assert lineas == ["system-view", "interface GE0/0/24", "port trunk pvid vlan 531", "commit", "quit", "quit"]
    assert "" not in lineas


def test_huawei_solo_agregar_y_solo_quitar():
    assert "port trunk pvid vlan" not in " ".join(_hw_lineas(None, [600], []))
    assert _hw_lineas(None, [], [144])[2] == "undo port trunk allow-pass vlan 144"


def test_huawei_nunca_link_type_ni_confirmacion_ni_undo_all():
    for pvid, add, remove in ((531, [600], [144]), (531, [], []), (None, [600], []), (None, [], [144])):
        lineas = _hw_lineas(pvid, add, remove)
        assert not any("link-type" in l for l in lineas)
        assert "y" not in lineas
        assert not any("vlan all" in l for l in lineas)


def test_huawei_parte_listas_largas_en_tandas_de_10_items():
    vlans = [10 + 2 * i for i in range(12)]
    lineas = _hw_lineas(None, vlans, [])
    allow = [l for l in lineas if l.startswith("port trunk allow-pass vlan")]
    assert len(allow) == 2
    emitidas = [int(x) for l in allow for x in l.split()[4:]]
    assert emitidas == vlans


def test_huawei_exige_al_menos_una_parte():
    with pytest.raises(ValueError):
        _hw(None, [], [])


def test_huawei_alternativa_de_interfaz_usa_el_nombre_completo_y_conserva_las_lineas():
    bloque = _render(HuaweiVendor(), _hw(531, [600], [144]), alternativa=0)["command_block"].split("\n")
    assert bloque[:2] == ["system-view", "interface GigabitEthernet0/0/24"]
    assert bloque[2:5] == [
        "port trunk allow-pass vlan 600", "port trunk pvid vlan 531", "undo port trunk allow-pass vlan 144",
    ]
    assert "commit" not in bloque


def test_huawei_alternativa_sin_commit_conserva_las_lineas():
    bloque = _render(HuaweiVendor(), _hw(531, [600], [144]), alternativa=1)["command_block"].split("\n")
    assert bloque == [
        "system-view", "interface GE0/0/24",
        "port trunk allow-pass vlan 600", "port trunk pvid vlan 531", "undo port trunk allow-pass vlan 144",
        "quit", "quit",
    ]


def test_huawei_las_alternativas_repiten_el_mismo_repeat_que_el_primary():
    entry = HuaweiVendor()._cargar_comandos()["set_trunk_config_delta"]
    for alt in entry["alternatives"]:
        assert alt["repeat"] == entry["primary"]["repeat"]


def test_huawei_trigger_de_interfaz_matchea_el_error_real():
    entry = HuaweiVendor()._cargar_comandos()["set_trunk_config_delta"]
    error_real = (
        "[~swhw02]interface GE0/0/24\r\n"
        "                  ^\r\n"
        "Error: Wrong parameter found at '^' position.\r\n"
    )
    assert re.search(entry["alternatives"][0]["triggered_by_error"], error_real)


def _ci(pvid, add, remove, interface="Gi0/1"):
    return CiscoVendor().resolver_set_trunk_config_delta(interface, pvid, add, remove)


def test_cisco_los_tres_juntos_en_orden_add_native_remove():
    extravars = _render(CiscoVendor(), _ci(531, [600, 601, 700], [144]))
    assert extravars["parents"] == "interface Gi0/1"
    assert extravars["lines"] == [
        "switchport trunk allowed vlan add 600-601,700",
        "switchport trunk native vlan 531",
        "switchport trunk allowed vlan remove 144",
    ]
    assert extravars["match"] == "none"


def test_cisco_solo_native():
    assert _render(CiscoVendor(), _ci(531, [], []))["lines"] == ["switchport trunk native vlan 531"]


def test_cisco_nunca_switchport_mode_ni_lista_completa():
    for pvid, add, remove in ((531, [600], [144]), (531, [], []), (None, [600], []), (None, [], [144])):
        for l in _render(CiscoVendor(), _ci(pvid, add, remove))["lines"]:
            assert "switchport mode" not in l
            assert l.startswith((
                "switchport trunk native vlan ", "switchport trunk allowed vlan add ",
                "switchport trunk allowed vlan remove ",
            ))


def test_cisco_exige_al_menos_una_parte():
    with pytest.raises(ValueError):
        _ci(None, [], [])
