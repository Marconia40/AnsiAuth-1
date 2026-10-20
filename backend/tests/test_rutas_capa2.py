from __future__ import annotations

from app.services.parsers.global_config_parser import CiscoGlobalConfigParser

SHOW_IP_ROUTE_CAPA2 = (
    "Default gateway is 10.237.60.1\n"
    "\n"
    "Host               Gateway           Last Use    Total Uses  Interface\n"
    "ICMP redirect cache is empty\n"
)
RUNNING_CAPA2 = "hostname swcs02\n!\nip default-gateway 10.237.60.1\n!\nend\n"


def test_switch_capa2_muestra_el_default_gateway():
    config = CiscoGlobalConfigParser.parse(route_output=SHOW_IP_ROUTE_CAPA2, running_config_output=RUNNING_CAPA2)
    assert config.routes == [
        {"destination": None, "next_hop": "10.237.60.1", "interface": None, "tipo": "default-gateway"},
    ]


def test_sin_rutas_es_lista_vacia_y_no_sin_datos():
    config = CiscoGlobalConfigParser.parse(
        route_output="Gateway of last resort is not set\n\n",
        running_config_output="hostname sw\n!\nend\n",
    )
    assert config.routes == []


def test_sin_salida_que_analizar_es_sin_datos():
    assert CiscoGlobalConfigParser.parse().routes is None


def test_el_gateway_no_se_confunde_con_una_ruta_por_defecto():
    config = CiscoGlobalConfigParser.parse(
        route_output=SHOW_IP_ROUTE_CAPA2,
        running_config_output=RUNNING_CAPA2 + "ip route 10.0.0.0 255.0.0.0 10.237.60.1\n",
    )
    destinos = [r["destination"] for r in config.routes]
    assert "0.0.0.0/0" not in destinos
    assert "10.0.0.0/8" in destinos


def test_switch_capa3_ignora_un_default_gateway_sin_efecto():
    tabla = (
        "Gateway of last resort is 10.0.0.1 to network 0.0.0.0\n"
        "\n"
        "S*    0.0.0.0/0 [1/0] via 10.0.0.1\n"
        "C        10.0.0.0/24 is directly connected, Vlan10\n"
    )
    config = CiscoGlobalConfigParser.parse(
        route_output=tabla,
        running_config_output="ip routing\nip default-gateway 10.237.60.1\nip route 0.0.0.0 0.0.0.0 10.0.0.1\n",
    )
    assert all(r.get("tipo") != "default-gateway" for r in config.routes)
    assert {"destination": "0.0.0.0/0", "next_hop": "10.0.0.1", "interface": None} in config.routes
