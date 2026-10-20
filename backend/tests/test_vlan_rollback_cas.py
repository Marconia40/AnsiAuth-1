from __future__ import annotations

import pytest

from app.models.vlan import VLAN
from tests._device_helper import device_con_driver as _device


class _Driver:
    def __init__(self, vlans=None, lectura_falla=False):
        self.vlans = dict(vlans or {})
        self.lectura_falla = lectura_falla
        self.calls: list = []

    def get_vlans(self, device, password):
        if self.lectura_falla:
            raise RuntimeError("sin acceso")
        return [VLAN(vlan_id=i, name=n) for i, n in self.vlans.items()]

    def resolver_create_vlan(self, vlan_id, name):
        return ("create_vlan", None, {"vlan_id": vlan_id, "name": name})

    def resolver_update_vlan(self, vlan_id, name):
        return ("update_vlan", None, {"vlan_id": vlan_id, "name": name})

    def resolver_delete_vlan(self, vlan_id):
        return ("delete_vlan", None, {"vlan_id": vlan_id})

    def create_vlan(self, vlan_id, name, device, password):
        self.calls.append(("create", vlan_id, name)); self.vlans[vlan_id] = name
        return {"rc": 0}

    def update_vlan(self, vlan_id, name, device, password):
        self.calls.append(("update", vlan_id, name)); self.vlans[vlan_id] = name
        return {"rc": 0}

    def delete_vlan(self, vlan_id, device, password):
        self.calls.append(("delete", vlan_id)); self.vlans.pop(vlan_id, None)
        return {"rc": 0}


def _pre(existed, name=None) -> dict:
    return {"existed": existed, "name": name}


def _ahora(name):
    return None if name is None else VLAN(vlan_id=100, name=name)


@pytest.mark.parametrize("ahora, revierte", [
    ("nueva", True),
    (None, False),
    ("de-un-tercero", False),
])
def test_crear_se_borra_solo_si_sigue_siendo_la_que_creo_el_cambio(ahora, revierte):
    pasos, verificar = VLAN(vlan_id=100, name="nueva").resolver_rollback(
        _pre(False), _device(_Driver()), _ahora(ahora),
    )
    if revierte:
        assert pasos == [("delete_vlan", None, {"vlan_id": 100})]
        assert verificar(None) is True and verificar(_ahora("nueva")) is False
    else:
        assert pasos == [] and verificar is None


@pytest.mark.parametrize("ahora, revierte", [
    ("nombre-nuevo", True),
    ("nombre-viejo", False),
    ("de-un-tercero", False),
    (None, False),
])
def test_renombrar_se_restaura_solo_si_sigue_el_nombre_que_puso_el_cambio(ahora, revierte):
    pasos, verificar = VLAN(vlan_id=100, name="nombre-nuevo").resolver_rollback(
        _pre(True, "nombre-viejo"), _device(_Driver()), _ahora(ahora),
    )
    if revierte:
        assert pasos == [("update_vlan", None, {"vlan_id": 100, "name": "nombre-viejo"})]
        assert verificar(_ahora("nombre-viejo")) is True and verificar(_ahora("nombre-nuevo")) is False
    else:
        assert pasos == []


@pytest.mark.parametrize("ahora, revierte", [
    (None, True),
    ("existe", False),
])
def test_borrar_se_recrea_solo_si_sigue_sin_existir(ahora, revierte):
    pasos, verificar = VLAN(vlan_id=100, eliminar=True).resolver_rollback(
        _pre(True, "prod"), _device(_Driver()), _ahora(ahora),
    )
    if revierte:
        assert pasos == [("create_vlan", None, {"vlan_id": 100, "name": "prod"})]
        assert verificar(_ahora("prod")) is True and verificar(None) is False
    else:
        assert pasos == []


def test_borrar_algo_que_no_existia_no_recrea_nada():
    assert VLAN(vlan_id=100, eliminar=True).resolver_rollback(_pre(False), _device(_Driver()), None)[0] == []


def test_la_clase_pide_lectura_fresca_al_orquestador():
    assert VLAN.NECESITA_ESTADO_FRESCO_ROLLBACK is True


def _single(cambio: VLAN, pre: dict, vlans: dict, **kw):
    drv = _Driver(vlans, **kw)
    return cambio.ejecutar_rollback(pre, _device(drv)), drv


def test_single_crear_borra_la_que_creo_el_cambio():
    res, drv = _single(VLAN(vlan_id=100, name="nueva"), _pre(False), {100: "nueva"})
    assert res == (True, True) and drv.calls == [("delete", 100)]


@pytest.mark.parametrize("vlans", [{}, {100: "de-un-tercero"}])
def test_single_crear_no_toca_nada_si_no_existe_o_es_de_un_tercero(vlans):
    res, drv = _single(VLAN(vlan_id=100, name="nueva"), _pre(False), vlans)
    assert res == (False, None) and drv.calls == []


def test_single_crear_sin_poder_leer_no_borra_a_ciegas():
    res, drv = _single(VLAN(vlan_id=100, name="nueva"), _pre(False), {100: "nueva"}, lectura_falla=True)
    assert res == (False, None) and drv.calls == []


def test_single_renombrar_restaura_solo_si_sigue_el_nombre_del_cambio():
    res, drv = _single(VLAN(vlan_id=100, name="nuevo"), _pre(True, "viejo"), {100: "nuevo"})
    assert res == (True, True) and drv.vlans[100] == "viejo"
    res, drv = _single(VLAN(vlan_id=100, name="nuevo"), _pre(True, "viejo"), {100: "de-un-tercero"})
    assert res == (False, None) and drv.calls == []


def test_single_borrar_recrea_aunque_no_se_pueda_leer():
    res, drv = _single(VLAN(vlan_id=100, eliminar=True), _pre(True, "prod"), {}, lectura_falla=True)
    assert drv.calls == [("create", 100, "prod")]
    assert res[0] is True


def test_single_borrar_no_recrea_si_ya_existe():
    res, drv = _single(VLAN(vlan_id=100, eliminar=True), _pre(True, "prod"), {100: "prod"})
    assert res == (False, None) and drv.calls == []
