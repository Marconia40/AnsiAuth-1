from __future__ import annotations

from app.services.vendors.cisco.driver import CiscoVendor


def _render(paso, *, alternativa: "int | None" = None) -> dict:
    driver = CiscoVendor()
    op_key, variant, vars = paso
    entry = driver._cargar_comandos()[op_key]
    entry = entry if variant is None else entry[variant]
    step = entry["primary"] if alternativa is None else entry["alternatives"][alternativa]
    return driver._renderizar_paso(step, vars)


def test_access_borra_native_y_allowed_del_trunk():
    extravars = _render(CiscoVendor().resolver_set_access_mode("Gi1/0/5", 814))
    assert extravars["parents"] == "interface Gi1/0/5"
    assert extravars["lines"] == [
        "switchport mode access",
        "switchport access vlan 814",
        "no switchport trunk native vlan",
        "no switchport trunk allowed vlan",
    ]


def test_trunk_borra_la_vlan_de_access():
    paso = CiscoVendor().resolver_set_trunk_mode("Gi1/0/5", 155, [206, 212, 213])
    assert _render(paso)["lines"] == [
        "switchport mode trunk",
        "switchport trunk native vlan 155",
        "switchport trunk allowed vlan 206,212-213",
        "no switchport access vlan",
    ]
    assert _render(paso, alternativa=0)["lines"][-1] == "no switchport access vlan"
