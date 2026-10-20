from __future__ import annotations

import pytest

from app.models.port import Puerto

from tests._puerto_fakes import FakePuertoDriver

_IFACE = "GigabitEthernet0/0/24"


def _trunk(vlans: "list[int] | None", pvid: "int | None" = 1) -> Puerto:
    return Puerto(interface=_IFACE, mode="trunk", access_vlan=pvid, allowed_vlans=vlans)


def _device(ports: "list[Puerto]"):
    class _Dev:
        name = "tm_dev"
        vendor = "huawei_vrp"
        password = "pw"
        driver = FakePuertoDriver(ports=ports, stateful=True)
    return _Dev()


def _quiero(pvid: int, vlans: "list[int]") -> Puerto:
    return Puerto(interface=_IFACE, mode="trunk", access_vlan=pvid, allowed_vlans=vlans)


def _paso(actual: "Puerto | None", pvid: int, vlans: "list[int]"):
    return _quiero(pvid, vlans).resolver_paso(_device([_trunk([10])]), actual)


def test_ya_coincide_todo_no_manda_nada():
    assert _paso(_trunk([10, 20, 30]), 1, [10, 20, 30]) is None


def test_solo_agregar():
    op, _v, vars = _paso(_trunk([10, 20, 30]), 1, [10, 20, 30, 40])
    assert op == "set_trunk_config_delta"
    assert (vars["pvid"], vars["add"], vars["remove"]) == (None, [40], [])


def test_solo_quitar_aunque_allowed_vlan_operation_sea_add():
    assert _quiero(1, [10]).allowed_vlan_operation == "add"
    _op, _v, vars = _paso(_trunk([10, 20]), 1, [10])
    assert (vars["pvid"], vars["add"], vars["remove"]) == (None, [], [20])


def test_solo_pvid():
    _op, _v, vars = _paso(_trunk([10, 20, 30]), 5, [10, 20, 30])
    assert (vars["pvid"], vars["add"], vars["remove"]) == (5, [], [])


def test_pvid_mas_agregar_y_quitar():
    _op, _v, vars = _paso(_trunk([10, 20, 30]), 5, [30, 40])
    assert (vars["pvid"], vars["add"], vars["remove"]) == (5, [40], [10, 20])


def test_pvid_actual_desconocido_cuenta_como_distinto():
    _op, _v, vars = _paso(_trunk([10, 20], pvid=None), 5, [10, 20])
    assert vars["pvid"] == 5


def test_lista_vacia_leida_es_un_estado_valido():
    _op, _v, vars = _paso(_trunk([]), 1, [10, 20])
    assert (vars["add"], vars["remove"]) == ([10, 20], [])


@pytest.mark.parametrize("actual", [
    Puerto(interface=_IFACE, mode="access", access_vlan=10),
    Puerto(interface=_IFACE, mode="unknown", access_vlan=1),
    Puerto(interface=_IFACE, mode="trunk", access_vlan=1, allowed_vlans=None),
    None,
])
def test_sin_base_para_un_delta_es_el_bloque_completo(actual):
    op, _v, vars = _paso(actual, 1, [10, 20])
    assert op == "set_trunk_mode"
    assert (vars["native_vlan"], vars["vlan_list"]) == (1, [10, 20])


def test_aplicar_con_pre_state_manda_el_delta_y_devuelve_la_accion():
    dev = _device([_trunk([10, 20, 30])])
    resultado = _quiero(1, [10, 20, 30, 40]).aplicar(dev, pre_state={"existed": True, "actual": _trunk([10, 20, 30])})
    assert resultado["success"] is True
    assert resultado["accion"] == "configurar_modo_trunk"
    assert dev.driver.ports[0].allowed_vlans == [10, 20, 30, 40]
    assert [op for op, _v, _vars in dev.driver.calls] == ["set_trunk_config_delta"]


def test_aplicar_sin_pre_state_relee_el_estado_como_en_un_reintento():
    dev = _device([_trunk([10, 20, 30])])
    resultado = _quiero(1, [10, 20, 30, 40]).aplicar(dev)
    assert resultado["success"] is True
    assert dev.driver.ports[0].allowed_vlans == [10, 20, 30, 40]
    assert [op for op, _v, _vars in dev.driver.calls] == ["set_trunk_config_delta"]


def test_aplicar_idempotente_no_manda_nada():
    dev = _device([_trunk([10, 20, 30])])
    resultado = _quiero(1, [10, 20, 30]).aplicar(dev)
    assert resultado["noop"] is True
    assert resultado["accion"] == "configurar_modo_trunk"
    assert dev.driver.calls == []


def test_aplicar_desde_access_sigue_siendo_el_bloque_completo():
    dev = _device([Puerto(interface=_IFACE, mode="access", access_vlan=10)])
    _quiero(1, [10, 20]).aplicar(dev)
    assert [op for op, _v, _vars in dev.driver.calls] == ["set_trunk_mode"]


def _pre(vlans, pvid=1):
    return {"existed": True, "actual": _trunk(vlans, pvid)}


def _plan(quiero: Puerto, previas, pvid_previo, ahora):
    return quiero.resolver_rollback(_pre(previas, pvid_previo), _device([_trunk([10])]), ahora)


def _campos(pasos):
    assert len(pasos) == 1
    op, _v, vars = pasos[0]
    assert op == "set_trunk_config_delta"
    return vars["pvid"], vars["add"], vars["remove"]


def test_rollback_aplicado_deshace_pvid_y_lista_en_un_paso():
    pasos, _ = _plan(_quiero(5, [30, 40, 50]), [10, 20, 30], 1, _trunk([30, 40, 50], pvid=5))
    assert _campos(pasos) == (1, [10, 20], [40, 50])


def test_rollback_no_pisa_un_pvid_cambiado_por_un_tercero():
    pasos, _ = _plan(_quiero(5, [30, 40, 50]), [10, 20, 30], 1, _trunk([30, 40, 50], pvid=9))
    assert _campos(pasos) == (None, [10, 20], [40, 50])


def test_rollback_conserva_una_vlan_de_un_tercero():
    pasos, _ = _plan(_quiero(1, [10, 20, 30, 40]), [10, 20, 30], 1, _trunk([10, 20, 30, 40, 700]))
    assert _campos(pasos) == (None, [], [40])


def test_rollback_de_un_apply_que_nunca_se_aplico_no_hace_nada():
    pasos, verificar = _plan(_quiero(5, [10, 20, 30, 40]), [10, 20, 30], 1, _trunk([10, 20, 30], pvid=1))
    assert pasos == []
    assert verificar is None


def test_rollback_sin_lectura_fresca_es_incondicional_pero_incremental():
    pasos, _ = _plan(_quiero(5, [30, 40]), [10, 20, 30], 1, None)
    assert _campos(pasos) == (1, [10, 20], [40])


def test_rollback_con_pvid_anterior_desconocido_no_restaura_el_pvid():
    pasos, _ = _plan(_quiero(5, [30, 40]), [10, 20, 30], None, _trunk([30, 40], pvid=5))
    assert _campos(pasos) == (None, [10, 20], [40])


def test_rollback_con_lista_anterior_vacia_quita_todo_lo_agregado():
    pasos, _ = _plan(_quiero(1, [10, 20]), [], 1, _trunk([10, 20]))
    assert _campos(pasos) == (None, [], [10, 20])


def test_rollback_no_toca_un_puerto_que_ya_no_es_trunk():
    ahora = Puerto(interface=_IFACE, mode="access", access_vlan=10)
    pasos, _ = _plan(_quiero(5, [30, 40]), [10, 20, 30], 1, ahora)
    assert pasos == []


def test_rollback_nunca_es_el_bloque_completo_ni_undo_all():
    for ahora in (_trunk([30, 40], pvid=5), None, _trunk([30, 40], pvid=9)):
        pasos, _ = _plan(_quiero(5, [30, 40]), [10, 20, 30], 1, ahora)
        assert all(p[0] == "set_trunk_config_delta" for p in pasos)


def test_rollback_de_access_a_trunk_sigue_siendo_set_access_mode():
    anterior = {"existed": True, "actual": Puerto(interface=_IFACE, mode="access", access_vlan=10)}
    pasos, _ = _quiero(1, [10, 20]).resolver_rollback(anterior, _device([_trunk([10])]), _trunk([10, 20]))
    assert [p[0] for p in pasos] == ["set_access_mode"]


def test_rollback_de_trunk_a_access_sigue_siendo_set_trunk_mode():
    p = Puerto(interface=_IFACE, mode="access", access_vlan=20)
    pasos, _ = p.resolver_rollback(_pre([10, 20, 30]), _device([_trunk([10])]), None)
    assert [x[0] for x in pasos] == ["set_trunk_mode"]


def test_rollback_de_trunk_con_lista_no_leida_no_hace_nada_como_antes():
    pasos, _ = _plan(_quiero(5, [30]), None, 1, _trunk([30], pvid=5))
    assert pasos == []


def test_verificador_ignora_una_vlan_de_un_tercero():
    _, verificar = _plan(_quiero(1, [10, 20, 30, 40]), [10, 20, 30], 1, _trunk([10, 20, 30, 40]))
    assert verificar(_trunk([10, 20, 30, 700])) is True


def test_verificador_exige_el_pvid_restaurado():
    _, verificar = _plan(_quiero(5, [30, 40]), [10, 20, 30], 1, _trunk([30, 40], pvid=5))
    assert verificar(_trunk([10, 20, 30], pvid=1)) is True
    assert verificar(_trunk([10, 20, 30], pvid=5)) is False


def test_verificador_no_exige_el_pvid_si_no_se_restauro():
    _, verificar = _plan(_quiero(5, [30, 40]), [10, 20, 30], 1, _trunk([30, 40], pvid=9))
    assert verificar(_trunk([10, 20, 30], pvid=9)) is True


def test_verificador_falla_si_falta_una_vlan_quitada():
    _, verificar = _plan(_quiero(1, [10, 30]), [10, 20, 30], 1, _trunk([10, 30]))
    assert verificar(_trunk([10, 30])) is False


def test_ejecutar_rollback_restaura_pvid_y_lista_y_conserva_al_tercero():
    dev = _device([_trunk([30, 40, 700], pvid=5)])
    performed, success = _quiero(5, [30, 40]).ejecutar_rollback(_pre([10, 20, 30], 1), dev)

    assert (performed, success) == (True, True)
    assert dev.driver.ports[0].access_vlan == 1
    assert dev.driver.ports[0].allowed_vlans == [10, 20, 30, 700]
    assert [op for op, _v, _vars in dev.driver.calls] == ["set_trunk_config_delta"]


def test_ejecutar_rollback_no_pisa_el_pvid_de_un_tercero():
    dev = _device([_trunk([30, 40], pvid=9)])
    assert _quiero(5, [30, 40]).ejecutar_rollback(_pre([10, 20, 30], 1), dev) == (True, True)
    assert dev.driver.ports[0].access_vlan == 9
    assert dev.driver.ports[0].allowed_vlans == [10, 20, 30]


def test_ejecutar_rollback_sin_nada_que_deshacer_no_escribe():
    dev = _device([_trunk([10, 20, 30], pvid=1)])
    assert _quiero(5, [10, 20, 30, 40]).ejecutar_rollback(_pre([10, 20, 30], 1), dev) == (False, None)
    assert dev.driver.calls == []


def test_ejecutar_rollback_paso_rechazado_es_intentado_y_fallido():
    dev = _device([_trunk([30, 40], pvid=5)])
    dev.driver.fail_on = lambda op_key, vars: op_key == "set_trunk_config_delta"
    assert _quiero(5, [30, 40]).ejecutar_rollback(_pre([10, 20, 30], 1), dev) == (True, False)


def test_ejecutar_rollback_de_trunk_a_access_no_cambia():
    dev = _device([Puerto(interface=_IFACE, mode="access", access_vlan=20)])
    p = Puerto(interface=_IFACE, mode="access", access_vlan=20)
    assert p.ejecutar_rollback(_pre([10, 20, 30], 1), dev) == (True, True)
    assert [op for op, _v, _vars in dev.driver.calls] == ["rollback:set_trunk_mode"]


def test_e2e_apply_falla_a_mitad_y_el_rollback_deja_el_trunk_como_estaba(admin_client, monkeypatch):
    from app.composition import job_repository, plugin_registry
    from tests._puerto_fakes import get_or_create_device

    drv = FakePuertoDriver(stateful=True, mutate_before_fail=True)
    drv.fail_on = lambda op_key, vars: op_key == "set_trunk_config_delta" and vars.get("pvid") == 5
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    dev = get_or_create_device("tm_e2e_dev", site_name="Trunk Mode Delta Site")

    res = admin_client.post(
        f"/api/v1/devices/{dev.name}/ports/trunk-mode",
        json={"interface": _IFACE, "native_vlan": 5, "allowed_vlans": [30, 40]},
    )
    assert res.status_code == 202, res.text
    job = job_repository.get(res.json()["data"]["jobs"][0]["job_id"])

    assert job.status == "failed"
    assert job.rollback_performed is True
    assert job.rollback_success is True
    trunk = next(p for p in drv.ports if p.interface == _IFACE)
    assert (trunk.access_vlan, trunk.allowed_vlans) == (1, [10, 20, 30])
    assert not any(op in ("set_trunk_mode", "rollback:set_trunk_mode") for op, _v, _vars in drv.calls)
