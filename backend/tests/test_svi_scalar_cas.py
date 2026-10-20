from __future__ import annotations

import pytest

from app.models.svi import SVI
from tests._device_helper import device_con_driver as _device

VLAN = 50


class _Driver:
    def __init__(self, lectura_falla=False, **estado):
        self.s = dict(description=None, admin_up=True, ipv4_address="10.0.0.1/24",
                      ipv6_address=None, ipv4_address_secondary=None)
        self.s.update(estado)
        self.lectura_falla = lectura_falla
        self.calls: list = []

    def get_svis(self, device, password):
        if self.lectura_falla:
            raise RuntimeError("sin acceso")
        return [SVI(vlan_id=VLAN, device="swcs01", **self.s)]

    def resolver_set_svi_description(self, vlan_id, desc):
        return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})

    def resolver_set_svi_admin_state(self, vlan_id, enabled):
        return ("set_svi_admin_state", None, {"vlan_id": vlan_id, "enabled": enabled})

    def resolver_set_svi_ipv4(self, vlan_id, ip):
        return ("set_svi_ipv4", None, {"vlan_id": vlan_id, "ip": ip})

    def resolver_set_svi_ipv6(self, vlan_id, ip):
        return ("set_svi_ipv6", None, {"vlan_id": vlan_id, "ip": ip})

    def aplicar_paso(self, op_key, variant, vars, device, password):
        self.calls.append((op_key, vars))
        campo = {"set_svi_description": "description", "set_svi_admin_state": "admin_up",
                 "set_svi_ipv4": "ipv4_address", "set_svi_ipv6": "ipv6_address"}[op_key]
        self.s[campo] = next(v for k, v in vars.items() if k != "vlan_id")
        return {"rc": 0}

    def set_svi_description(self, vlan_id, desc, device, password):
        self.calls.append(("set_svi_description", desc)); self.s["description"] = desc
        return {"rc": 0}

    def set_svi_admin_state(self, vlan_id, enabled, device, password):
        self.calls.append(("set_svi_admin_state", enabled)); self.s["admin_up"] = enabled
        return {"rc": 0}

    def set_svi_ipv4(self, vlan_id, ip, device, password):
        self.calls.append(("set_svi_ipv4", ip)); self.s["ipv4_address"] = ip
        return {"rc": 0}

    def set_svi_ipv6(self, vlan_id, ip, device, password):
        self.calls.append(("set_svi_ipv6", ip)); self.s["ipv6_address"] = ip
        return {"rc": 0}

    def set_svi_ipv4_secondary(self, vlan_id, add, remove, device, password):
        self.calls.append(("set_svi_ipv4_secondary", add, remove))
        lista = list(self.s["ipv4_address_secondary"] or [])
        if remove in lista:
            lista.remove(remove)
        if add and add not in lista:
            lista.append(add)
        self.s["ipv4_address_secondary"] = lista or None
        return {"rc": 0}


def _svi(**k) -> SVI:
    return SVI(vlan_id=VLAN, device="swcs01", **k)


def _pre(**k) -> dict:
    return {"existed": True, "actual": SVI(vlan_id=VLAN, device="swcs01", **k)}


def _ahora(**k) -> SVI:
    return SVI(vlan_id=VLAN, device="swcs01", **k)


CASOS = [
    ("description", "nueva", "vieja", "de-un-tercero", "set_svi_description"),
    ("admin_up", False, True, None, "set_svi_admin_state"),
    ("ipv4_address", "10.9.9.1/24", "10.0.0.1/24", "10.7.7.1/24", "set_svi_ipv4"),
    ("ipv6_address", "2001:db8::1/64", "2001:db8:1::1/64", "2001:db8:2::1/64", "set_svi_ipv6"),
]


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", CASOS)
def test_lote_revierte_si_sigue_lo_que_puso_el_cambio(campo, puesto, previo, tercero, op):
    pasos, verificar = _svi(**{campo: puesto}).resolver_rollback(
        _pre(**{campo: previo}), _device(_Driver()), _ahora(**{campo: puesto}),
    )
    assert [p[0] for p in pasos] == [op]
    assert verificar(_ahora(**{campo: previo})) is True
    assert verificar(_ahora(**{campo: puesto})) is False


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", CASOS)
def test_lote_no_toca_nada_si_ya_es_el_previo(campo, puesto, previo, tercero, op):
    assert _svi(**{campo: puesto}).resolver_rollback(
        _pre(**{campo: previo}), _device(_Driver()), _ahora(**{campo: previo}),
    )[0] == []


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", [c for c in CASOS if c[3] is not None])
def test_lote_no_pisa_lo_que_cambio_un_tercero(campo, puesto, previo, tercero, op):
    assert _svi(**{campo: puesto}).resolver_rollback(
        _pre(**{campo: previo}), _device(_Driver()), _ahora(**{campo: tercero}),
    )[0] == []


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", CASOS)
def test_lote_sin_lectura_fresca_revierte_como_siempre(campo, puesto, previo, tercero, op):
    pasos, _ = _svi(**{campo: puesto}).resolver_rollback(_pre(**{campo: previo}), _device(_Driver()), None)
    assert [p[0] for p in pasos] == [op]


def test_lote_admin_up_ilegible_ahora_revierte_como_siempre():
    pasos, _ = _svi(admin_up=False).resolver_rollback(
        _pre(admin_up=True), _device(_Driver()), _ahora(admin_up=None),
    )
    assert [p[0] for p in pasos] == ["set_svi_admin_state"]


def test_lote_texto_vacio_y_none_son_lo_mismo():
    pasos, _ = _svi(description="").resolver_rollback(
        _pre(description="vieja"), _device(_Driver()), _ahora(description=None),
    )
    assert [p[0] for p in pasos] == ["set_svi_description"]
    assert _svi(description="nueva").resolver_rollback(
        _pre(description=None), _device(_Driver()), _ahora(description=None),
    )[0] == []


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", CASOS)
def test_single_revierte_si_sigue_lo_que_puso_el_cambio(campo, puesto, previo, tercero, op):
    drv = _Driver(**{campo: puesto})
    res = _svi(**{campo: puesto}).ejecutar_rollback(_pre(**{campo: previo}), _device(drv))
    assert res == (True, True)
    assert [c[0] for c in drv.calls] == [op] and drv.s[campo] == previo


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", CASOS)
def test_single_no_toca_nada_si_ya_es_el_previo(campo, puesto, previo, tercero, op):
    drv = _Driver(**{campo: previo})
    assert _svi(**{campo: puesto}).ejecutar_rollback(_pre(**{campo: previo}), _device(drv)) == (False, None)
    assert drv.calls == []


@pytest.mark.parametrize("campo, puesto, previo, tercero, op", [c for c in CASOS if c[3] is not None])
def test_single_no_pisa_lo_que_cambio_un_tercero(campo, puesto, previo, tercero, op):
    drv = _Driver(**{campo: tercero})
    assert _svi(**{campo: puesto}).ejecutar_rollback(_pre(**{campo: previo}), _device(drv)) == (False, None)
    assert drv.calls == [] and drv.s[campo] == tercero


def test_single_sin_poder_leer_revierte_como_siempre():
    drv = _Driver(lectura_falla=True, admin_up=False)
    res = _svi(admin_up=False).ejecutar_rollback(_pre(admin_up=True), _device(drv))
    assert [c[0] for c in drv.calls] == ["set_svi_admin_state"] and res[0] is True


def test_single_secundaria_add_verifica_solo_la_ip_del_cambio():
    drv = _Driver(ipv4_address_secondary=["10.9.9.1/24", "10.6.6.1/24"])
    res = _svi(ipv4_secondary_add="10.9.9.1/24").ejecutar_rollback(
        _pre(ipv4_address_secondary=None), _device(drv),
    )
    assert res == (True, True) and drv.s["ipv4_address_secondary"] == ["10.6.6.1/24"]


def test_secundaria_verificador_lote_y_single_coinciden():
    add = _svi(ipv4_secondary_add="10.9.9.1/24")
    rm = _svi(ipv4_secondary_remove="10.9.9.1/24")
    con, sin = _ahora(ipv4_address_secondary=["10.9.9.1/24", "10.6.6.1/24"]), _ahora(ipv4_address_secondary=["10.6.6.1/24"])
    assert add._verificar_secundaria("ipv4_secondary_add", sin) is True
    assert add._verificar_secundaria("ipv4_secondary_add", con) is False
    assert rm._verificar_secundaria("ipv4_secondary_remove", con) is True
    assert rm._verificar_secundaria("ipv4_secondary_remove", sin) is False
    drv = _Driver()
    drv.resolver_set_svi_ipv4_secondary = lambda vlan_id, add, remove: ("set_svi_ipv4_secondary", None, {"remove": remove})
    _, verif = add.resolver_rollback(_pre(ipv4_address_secondary=[]), _device(drv), con)
    assert verif(sin) is True and verif(con) is False
