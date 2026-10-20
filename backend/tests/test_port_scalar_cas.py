from __future__ import annotations

import pytest

from app.models.port import Puerto

from tests._puerto_fakes import FakePuertoDriver
from tests._device_helper import device_con_driver as _device

IFACE = "Gi1/0/1"


def _p(**k) -> Puerto:
    return Puerto(interface=IFACE, device="swcs01", **k)


def _pre(**k) -> dict:
    return {"existed": True, "actual": _p(**k)}


def _plan(cambio: Puerto, pre: dict, ahora):
    return cambio.resolver_rollback(pre, _device(FakePuertoDriver()), ahora)


@pytest.mark.parametrize("ahora, revierte", [
    ("new", True),
    ("old", False),
    ("third-party", False),
])
def test_description(ahora, revierte):
    pasos, _ = _plan(_p(description="new"), _pre(description="old"), _p(description=ahora))
    if revierte:
        assert pasos == [("update_port_description", None, {"interface": IFACE, "description": "old"})]
    else:
        assert pasos == []


def test_description_clear_pedido_se_revierte_solo_si_sigue_vacia():
    assert _plan(_p(description=""), _pre(description="old"), _p(description=None))[0] != []
    assert _plan(_p(description=""), _pre(description="old"), _p(description="third-party"))[0] == []


@pytest.mark.parametrize("ahora, revierte", [(False, True), (True, False)])
def test_admin_up(ahora, revierte):
    pasos, _ = _plan(_p(admin_up=False), _pre(admin_up=True), _p(admin_up=ahora))
    assert (pasos == [("set_port_admin_state", None, {"interface": IFACE, "enabled": True})]) is revierte
    assert (pasos == []) is (not revierte)


def test_admin_up_ilegible_ahora_se_revierte_como_siempre():
    assert _plan(_p(admin_up=False), _pre(admin_up=True), _p(admin_up=None))[0] != []


@pytest.mark.parametrize("modo, op", [("access", "set_port_access_vlan"), ("trunk", "set_trunk_pvid_vlan")])
@pytest.mark.parametrize("ahora, revierte", [(44, True), (10, False), (77, False)])
def test_access_vlan_o_pvid(modo, op, ahora, revierte):
    pasos, _ = _plan(
        _p(access_vlan=44), _pre(mode=modo, access_vlan=10), _p(mode=modo, access_vlan=ahora),
    )
    if revierte:
        assert pasos == [(op, None, {"interface": IFACE, "vlan_id": 10})]
    else:
        assert pasos == []


def _storm(enabled, threshold=None, action=None, trap=None):
    return dict(
        storm_control_enabled=enabled, storm_control_threshold=threshold,
        storm_control_action=action, storm_control_trap=trap,
    )


@pytest.mark.parametrize("ahora, revierte", [
    (_storm(True, 20), True),
    (_storm(False), False),
    (_storm(True, 30), False),
    (_storm(True, 20, action="filter"), False),
    (_storm(True, 20, action="shutdown", trap=True), True),
])
def test_storm_control_de_deshabilitado_a_habilitado(ahora, revierte):
    pasos, _ = _plan(_p(**_storm(True, 20)), _pre(**_storm(False)), _p(**ahora))
    assert bool(pasos) is revierte
    if revierte:
        assert pasos[0][0] == "set_storm_control" and pasos[0][2]["enabled"] is False


def test_storm_control_restaura_action_y_trap_previos():
    pasos, _ = _plan(
        _p(**_storm(True, 20)),
        _pre(**_storm(True, 10, action="filter", trap=False)),
        _p(**_storm(True, 20)),
    )
    assert pasos == [("set_storm_control", None, {
        "interface": IFACE, "enabled": True, "threshold": 10, "action": "filter", "trap": False,
    })]


def test_storm_control_action_ilegible_no_cuenta_como_cambio_de_tercero():
    pasos, _ = _plan(
        _p(**_storm(True, 20, action="filter", trap=False)),
        _pre(**_storm(False)),
        _p(**_storm(True, 20, action=None, trap=None)),
    )
    assert pasos != []


def test_storm_control_deshabilitar_se_revierte_solo_si_sigue_deshabilitado():
    cambio, pre = _p(**_storm(False)), _pre(**_storm(True, 10))
    assert _plan(cambio, pre, _p(**_storm(False)))[0] != []
    assert _plan(cambio, pre, _p(**_storm(True, 50)))[0] == []


def test_sin_lectura_fresca_se_revierte_a_ciegas_como_antes():
    assert _plan(_p(description="new"), _pre(description="old"), None)[0] != []
    assert _plan(_p(admin_up=False), _pre(admin_up=True), None)[0] != []
    assert _plan(_p(access_vlan=44), _pre(mode="access", access_vlan=10), None)[0] != []
    assert _plan(_p(**_storm(True, 20)), _pre(**_storm(False)), None)[0] != []


def _single(cambio: Puerto, pre: dict, estado_actual: Puerto):
    drv = FakePuertoDriver(ports=[estado_actual], stateful=True)
    resultado = cambio.ejecutar_rollback(pre, _device(drv))
    return resultado, drv


def test_single_revierte_cuando_sigue_lo_que_puso_el_cambio():
    res, drv = _single(_p(admin_up=False), _pre(admin_up=True), _p(admin_up=False))
    assert res == (True, True)
    assert [c[0] for c in drv.calls] == ["rollback:set_port_admin_state"]
    assert drv.ports[0].admin_up is True


@pytest.mark.parametrize("cambio, pre, estado", [
    (_p(admin_up=False), _pre(admin_up=True), _p(admin_up=True)),
    (_p(description="new"), _pre(description="old"), _p(description="third-party")),
    (_p(access_vlan=44), _pre(mode="access", access_vlan=10), _p(mode="access", access_vlan=77)),
    (_p(**_storm(True, 20)), _pre(**_storm(False)), _p(**_storm(True, 30))),
])
def test_single_no_toca_nada_si_ya_esta_como_antes_o_lo_cambio_un_tercero(cambio, pre, estado):
    res, drv = _single(cambio, pre, estado)
    assert res == (False, None)
    assert drv.calls == []
