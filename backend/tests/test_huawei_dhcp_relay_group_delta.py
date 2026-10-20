from __future__ import annotations

import pytest

from app.models.svi import SVI, DhcpRelayLayout
from app.services.parsers.svi_parser import HuaweiSVIParser
from app.services.vendors.huawei.driver import HuaweiVendor
from tests._device_helper import device_con_driver as _device


DHCP_CONFIG = """#
dhcp relay server group dhcpgrp01
 server 10.238.16.27 0
 server 10.238.16.37 1
#
dhcp relay server group compartido
 server 10.0.0.1 0
#
return
"""

INTERFACES = """#
interface Vlanif100
 description wifi
 ip address 10.100.0.1 255.255.255.0
 dhcp select relay
 dhcp relay binding server group dhcpgrp01
#
interface Vlanif200
 ip address 10.200.0.1 255.255.255.0
 dhcp select relay
 dhcp relay binding server group compartido
#
interface Vlanif201
 ip address 10.201.0.1 255.255.255.0
 dhcp select relay
 dhcp relay binding server group compartido
#
interface Vlanif300
 ip address 10.30.0.1 255.255.255.0
 dhcp select relay
 dhcp relay server-ip 10.9.9.9
#
interface Vlanif400
 ip address 10.40.0.1 255.255.255.0
#
"""

BRIEF = "".join(f"Vlanif{v}   10.0.0.1/24   up   up\n" for v in (100, 200, 201, 300, 400))


def _parse(con_entradas=True):
    grupos = HuaweiSVIParser.parse_dhcp_relay_groups(DHCP_CONFIG)
    entradas = HuaweiSVIParser.parse_dhcp_relay_group_entries(DHCP_CONFIG) if con_entradas else None
    return {
        s.vlan_id: s
        for s in HuaweiSVIParser.parse_svis(INTERFACES, BRIEF, dhcp_groups=grupos, dhcp_group_entries=entradas)
    }


def test_los_indices_de_cada_grupo_se_leen_junto_a_la_ip():
    assert HuaweiSVIParser.parse_dhcp_relay_group_entries(DHCP_CONFIG) == {
        "dhcpgrp01": {"10.238.16.27": 0, "10.238.16.37": 1},
        "compartido": {"10.0.0.1": 0},
    }
    assert HuaweiSVIParser.parse_dhcp_relay_groups(DHCP_CONFIG)["dhcpgrp01"] == ["10.238.16.27", "10.238.16.37"]


def test_grupo_usado_por_una_sola_interfaz_es_exclusivo():
    svi = _parse()[100]
    assert svi.dhcp_relay_servers == ["10.238.16.27", "10.238.16.37"]
    assert svi.dhcp_relay_layout == DhcpRelayLayout(
        forma="grupo", grupo="dhcpgrp01", indices={"10.238.16.27": 0, "10.238.16.37": 1}, exclusivo=True,
    )


def test_grupo_usado_por_dos_interfaces_no_es_exclusivo():
    svis = _parse()
    for vlan in (200, 201):
        layout = svis[vlan].dhcp_relay_layout
        assert layout.forma == "grupo" and layout.grupo == "compartido" and layout.exclusivo is False


def test_forma_directa_y_sin_relay():
    svis = _parse()
    assert svis[300].dhcp_relay_layout == DhcpRelayLayout(forma="directa")
    assert svis[400].dhcp_relay_layout is None and svis[400].dhcp_relay_servers is None


def test_sin_los_indices_del_grupo_nunca_es_exclusivo():
    layout = _parse(con_entradas=False)[100].dhcp_relay_layout
    assert layout.forma == "grupo" and layout.exclusivo is False and layout.indices == {}


def test_el_layout_no_afecta_la_igualdad_de_la_svi():
    assert _parse()[100] == SVI(
        vlan_id=100, description="wifi", admin_up=True, operational_up=True,
        ipv4_address="10.100.0.1/24", dhcp_relay_servers=["10.238.16.27", "10.238.16.37"],
    )


def test_agregar_usa_el_indice_libre_mas_bajo_y_nunca_uno_ocupado():
    layout = DhcpRelayLayout("grupo", "g", {"a": 0, "c": 2}, True)
    assert layout.asignar_indices(["b"]) == {"b": 1}
    assert layout.asignar_indices(["b", "d"]) == {"b": 1, "d": 3}


def test_el_indice_que_tenia_se_conserva_si_sigue_libre():
    layout = DhcpRelayLayout("grupo", "g", {"a": 0}, True)
    assert layout.asignar_indices(["b"], {"b": 5}) == {"b": 5}
    assert layout.asignar_indices(["b"], {"b": 0}) == {"b": 1}


def test_grupo_lleno_falla_en_vez_de_pisar():
    layout = DhcpRelayLayout("grupo", "g", {f"10.0.0.{i}": i for i in range(20)}, True)
    with pytest.raises(ValueError, match="full"):
        layout.asignar_indices(["10.9.9.9"])


def _paso(add, remove, final, layout, previos=None):
    return HuaweiVendor().resolver_set_svi_dhcp_relay_delta(
        100, add, remove, final, layout=layout, indices_previos=previos,
    )


def _render(paso, alternativa=None):
    op_key, variant, vars = paso
    entry = HuaweiVendor()._cargar_comandos()[op_key]
    entry = entry if variant is None else entry[variant]
    step = entry["primary"] if alternativa is None else entry["alternatives"][alternativa]
    return HuaweiVendor()._renderizar_paso(step, vars)["command_block"].split("\n")


GRUPO = DhcpRelayLayout("grupo", "dhcpgrp01", {"10.238.16.27": 0}, True)


def test_transcript_agregar_a_un_grupo_con_el_indice_0_ocupado_usa_el_1():
    paso = _paso(["10.238.16.37"], [], ["10.238.16.27", "10.238.16.37"], GRUPO)
    assert paso[0] == "set_svi_dhcp_relay_delta"
    assert _render(paso) == [
        "system-view", "dhcp relay server group dhcpgrp01", "server 10.238.16.37 1",
        "commit", "quit", "quit",
    ]


def test_transcript_quitar_es_por_ip_sin_indice():
    layout = DhcpRelayLayout("grupo", "dhcpgrp01", {"10.238.16.27": 0, "10.238.16.37": 1}, True)
    paso = _paso([], ["10.238.16.37"], ["10.238.16.27"], layout)
    assert _render(paso) == [
        "system-view", "dhcp relay server group dhcpgrp01", "undo server 10.238.16.37",
        "commit", "quit", "quit",
    ]


def test_reagregar_conserva_el_indice_que_tenia():
    layout = DhcpRelayLayout("grupo", "dhcpgrp01", {"10.238.16.27": 0}, True)
    paso = _paso(["10.238.16.37"], [], ["10.238.16.27", "10.238.16.37"], layout, {"10.238.16.37": 7})
    assert "server 10.238.16.37 7" in _render(paso)


def test_quitar_el_ultimo_server_del_grupo_deja_el_relay_de_la_interfaz_sin_borrar_el_grupo():
    layout = DhcpRelayLayout("grupo", "dhcpgrp01", {"10.238.16.27": 0}, True)
    lineas = _render(_paso([], ["10.238.16.27"], [], layout))
    assert lineas == [
        "system-view", "dhcp relay server group dhcpgrp01", "undo server 10.238.16.27",
        "quit", "interface Vlanif100", "undo dhcp select relay", "undo dhcp relay binding server group",
        "commit", "quit", "quit",
    ]
    assert not any(l.startswith("undo dhcp relay server group") for l in lineas)


def test_grupo_lleno_no_arma_el_comando():
    layout = DhcpRelayLayout("grupo", "g", {f"10.0.0.{i}": i for i in range(20)}, True)
    with pytest.raises(ValueError, match="full"):
        _paso(["10.9.9.9"], [], list(layout.indices) + ["10.9.9.9"], layout)


def test_forma_directa_agrega_y_quita_por_server():
    layout = DhcpRelayLayout("directa")
    assert _render(_paso(["10.1.1.1"], [], ["10.9.9.9", "10.1.1.1"], layout)) == [
        "system-view", "interface Vlanif100", "dhcp relay server-ip 10.1.1.1", "commit", "quit", "quit",
    ]
    assert _render(_paso([], ["10.1.1.1"], ["10.9.9.9"], layout)) == [
        "system-view", "interface Vlanif100", "undo dhcp relay server-ip 10.1.1.1", "commit", "quit", "quit",
    ]


@pytest.mark.parametrize("layout, final", [
    (None, ["a"]),
    (DhcpRelayLayout("grupo", "g", {"a": 0}, False), ["a"]),
    (DhcpRelayLayout("grupo", "g", {}, False), ["a"]),
    (DhcpRelayLayout("directa"), []),
])
def test_si_no_se_puede_editar_en_el_lugar_cae_al_reemplazo_completo_de_siempre(layout, final):
    paso = _paso(["a"], [], final, layout)
    assert paso == HuaweiVendor().resolver_set_svi_dhcp_relay(100, list(final))
    assert paso[0] == "set_svi_dhcp_relay"


def test_sin_commit_la_alternativa_manda_las_mismas_lineas():
    paso = _paso(["10.238.16.37"], [], ["10.238.16.27", "10.238.16.37"], GRUPO)
    assert _render(paso, alternativa=0) == [
        "system-view", "dhcp relay server group dhcpgrp01", "server 10.238.16.37 1", "quit", "quit",
    ]


class _Driver:
    def __init__(self):
        self.llamadas = []

    def resolver_set_svi_dhcp_relay_delta(self, vlan_id, add, remove, final, layout=None, indices_previos=None):
        self.llamadas.append({"add": add, "remove": remove, "final": final, "layout": layout, "previos": indices_previos})
        return ("delta", None, {})


def _svi_con(layout, servers):
    return SVI(vlan_id=100, device="swhw03", ipv4_address="10.100.0.1/24",
               dhcp_relay_servers=servers, dhcp_relay_layout=layout)


def test_el_apply_pasa_el_layout_de_la_lectura():
    drv = _Driver(); dev = _device(drv, vendor="huawei_vrp")
    SVI(vlan_id=100, dhcp_relay_add="10.238.16.37").resolver_paso(dev, _svi_con(GRUPO, ["10.238.16.27"]))
    SVI(vlan_id=100, dhcp_relay_remove="10.238.16.27").resolver_paso(dev, _svi_con(GRUPO, ["10.238.16.27"]))
    assert [c["layout"] for c in drv.llamadas] == [GRUPO, GRUPO]


def test_el_rollback_usa_el_layout_de_ahora_y_los_indices_de_antes():
    drv = _Driver(); dev = _device(drv, vendor="huawei_vrp")
    antes = DhcpRelayLayout("grupo", "dhcpgrp01", {"10.238.16.27": 0, "10.238.16.37": 1}, True)
    ahora = DhcpRelayLayout("grupo", "dhcpgrp01", {"10.238.16.27": 0}, True)
    SVI(vlan_id=100, dhcp_relay_remove="10.238.16.37").resolver_rollback(
        {"existed": True, "actual": _svi_con(antes, ["10.238.16.27", "10.238.16.37"])},
        dev, _svi_con(ahora, ["10.238.16.27"]),
    )
    llamada = drv.llamadas[-1]
    assert llamada["layout"] == ahora and llamada["previos"] == {"10.238.16.27": 0, "10.238.16.37": 1}
    assert llamada["add"] == ["10.238.16.37"] and llamada["remove"] == []


def test_el_restore_usa_el_layout_de_ahora():
    drv = _Driver(); dev = _device(drv, vendor="huawei_vrp")
    snap = SVI(vlan_id=100, dhcp_relay_servers=["10.238.16.27", "10.238.16.37"])
    snap.resolver_restore(dev, _svi_con(GRUPO, ["10.238.16.27"]))
    assert drv.llamadas[-1]["layout"] == GRUPO and drv.llamadas[-1]["add"] == ["10.238.16.37"]
