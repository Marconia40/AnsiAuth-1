from __future__ import annotations

import pytest

from app.composition import job_repository, plugin_registry
from app.models.port import Puerto
from app.services.parsers.port_parser import parse_vrp_port_vlan

from tests._puerto_fakes import FakePuertoDriver, get_or_create_device

_IFACE = "GigabitEthernet0/0/24"


def _device(ports: "list[Puerto]"):
    class _Dev:
        name = "rb_dev"
        vendor = "huawei_vrp"
        password = "pw"
        driver = FakePuertoDriver(ports=ports, stateful=True)
    return _Dev()


def _trunk(vlans: "list[int] | None", interface: str = _IFACE) -> Puerto:
    return Puerto(interface=interface, mode="trunk", access_vlan=1, allowed_vlans=vlans)


def _plan(operation: str, requested: "list[int]", previas: "list[int] | None", ahora: "list[int] | None | str"):
    p = Puerto(interface=_IFACE, allowed_vlans=requested, allowed_vlan_operation=operation)
    pre_state = {"existed": True, "actual": _trunk(previas)}
    actual_ahora = None if ahora is None else _trunk(ahora)
    dev = _device([_trunk(previas or [])])
    return p.resolver_rollback(pre_state, dev, actual_ahora)


def _delta_de(pasos):
    assert len(pasos) == 1
    op_key, _variant, vars = pasos[0]
    assert op_key == "set_trunk_vlans_delta"
    return vars["add"], vars["remove"]


def test_add_aplicado_se_deshace_quitando_solo_lo_agregado():
    pasos, _ = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 20, 30, 40])
    assert _delta_de(pasos) == ([], [40])


def test_add_que_nunca_se_aplico_no_hace_nada():
    pasos, verificar = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 20, 30])
    assert pasos == []
    assert verificar is None


def test_remove_aplicado_se_deshace_re_agregando_solo_lo_quitado():
    pasos, _ = _plan("remove", [20], previas=[10, 20, 30], ahora=[10, 30])
    assert _delta_de(pasos) == ([20], [])


def test_remove_que_nunca_se_aplico_no_hace_nada():
    pasos, _ = _plan("remove", [20], previas=[10, 20, 30], ahora=[10, 20, 30])
    assert pasos == []


def test_replace_aplicado_se_deshace_con_un_delta_inverso_no_con_undo_all():
    pasos, _ = _plan("replace", [30, 40], previas=[10, 20, 30], ahora=[30, 40])
    assert _delta_de(pasos) == ([10, 20], [40])
    assert pasos[0][1] == "both"


def test_una_vlan_agregada_por_un_tercero_no_se_toca():
    pasos, _ = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 20, 30, 40, 700])
    assert _delta_de(pasos) == ([], [40])


def test_una_vlan_que_un_tercero_quito_no_se_re_agrega_si_no_era_nuestra():
    pasos, _ = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 30, 40])
    assert _delta_de(pasos) == ([], [40])


@pytest.mark.parametrize("ahora", [[10, 20, 30, 40], [10, 20, 30], None])
def test_add_no_op_nunca_tiene_rollback(ahora):
    pasos, _ = _plan("add", [40], previas=[10, 40], ahora=ahora)
    assert pasos == []


def test_sin_lectura_fresca_el_inverso_es_incondicional_pero_incremental():
    pasos, _ = _plan("add", [40], previas=[10, 20, 30], ahora=None)
    assert _delta_de(pasos) == ([], [40])
    pasos, _ = _plan("remove", [20], previas=[10, 20, 30], ahora=None)
    assert _delta_de(pasos) == ([20], [])


@pytest.mark.parametrize("operation,requested,previas,ahora", [
    ("add", [40], [10, 20, 30], [10, 20, 30, 40]),
    ("remove", [20], [10, 20, 30], [10, 30]),
    ("replace", [30, 40], [10, 20, 30], [30, 40]),
    ("add", [40], [10, 20, 30], None),
])
def test_nunca_aparece_undo_all_ni_reemplazo_completo(operation, requested, previas, ahora):
    pasos, _ = _plan(operation, requested, previas, ahora)
    for op_key, _variant, _vars in pasos:
        assert op_key == "set_trunk_vlans_delta"


def test_puerto_que_ya_no_es_trunk_no_se_toca():
    p = Puerto(interface=_IFACE, allowed_vlans=[40], allowed_vlan_operation="add")
    pre_state = {"existed": True, "actual": _trunk([10, 20, 30])}
    ahora = Puerto(interface=_IFACE, mode="access", access_vlan=10)
    pasos, _ = p.resolver_rollback(pre_state, _device([_trunk([10])]), ahora)
    assert pasos == []


def test_pre_state_que_no_era_trunk_o_sin_lista_no_tiene_rollback():
    p = Puerto(interface=_IFACE, allowed_vlans=[40], allowed_vlan_operation="add")
    dev = _device([_trunk([10])])
    for anterior in (
        Puerto(interface=_IFACE, mode="access", access_vlan=10),
        _trunk(None),
    ):
        pasos, _ = p.resolver_rollback({"existed": True, "actual": anterior}, dev, None)
        assert pasos == []


def test_replace_sobre_estado_no_leido_no_tiene_delta_que_revertir():
    pasos, _ = _plan("replace", [10, 20], previas=None, ahora=[10, 20])
    assert pasos == []


def test_verificador_ignora_un_cambio_de_un_tercero_en_otra_vlan():
    _, verificar = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 20, 30, 40])
    assert verificar(_trunk([10, 20, 30, 700])) is True


def test_verificador_falla_si_la_vlan_agregada_sigue_presente():
    _, verificar = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 20, 30, 40])
    assert verificar(_trunk([10, 20, 30, 40])) is False


def test_verificador_falla_si_la_vlan_quitada_no_volvio():
    _, verificar = _plan("remove", [20], previas=[10, 20, 30], ahora=[10, 30])
    assert verificar(_trunk([10, 30])) is False
    assert verificar(_trunk([10, 20, 30])) is True


def test_verificador_lista_no_legible_confia_en_el_rc():
    _, verificar = _plan("add", [40], previas=[10, 20, 30], ahora=[10, 20, 30, 40])
    assert verificar(_trunk(None)) is True
    assert verificar(None) is False


def test_ejecutar_rollback_deshace_solo_lo_propio_y_conserva_al_tercero():
    dev = _device([_trunk([10, 20, 30, 40, 700])])
    p = Puerto(interface=_IFACE, allowed_vlans=[40], allowed_vlan_operation="add")
    pre_state = {"existed": True, "actual": _trunk([10, 20, 30])}

    performed, success = p.ejecutar_rollback(pre_state, dev)

    assert (performed, success) == (True, True)
    assert dev.driver.ports[0].allowed_vlans == [10, 20, 30, 700]
    assert [(op, v["add"], v["remove"]) for op, _va, v in dev.driver.calls] == [
        ("set_trunk_vlans_delta", [], [40]),
    ]


def test_ejecutar_rollback_no_abre_sesion_de_escritura_si_no_hay_nada_que_deshacer():
    dev = _device([_trunk([10, 20, 30])])
    p = Puerto(interface=_IFACE, allowed_vlans=[40], allowed_vlan_operation="add")
    pre_state = {"existed": True, "actual": _trunk([10, 20, 30])}

    assert p.ejecutar_rollback(pre_state, dev) == (False, None)
    assert dev.driver.calls == []


def test_ejecutar_rollback_sin_lectura_fresca_cae_al_inverso_incondicional():
    dev = _device([_trunk([10, 20, 30, 40])])
    lecturas = {"n": 0}
    real = dev.driver.list_ports

    def _flaky(device, password):
        lecturas["n"] += 1
        if lecturas["n"] == 1:
            raise RuntimeError("read failed")
        return real(device, password)

    dev.driver.list_ports = _flaky
    p = Puerto(interface=_IFACE, allowed_vlans=[40], allowed_vlan_operation="add")
    pre_state = {"existed": True, "actual": _trunk([10, 20, 30])}

    assert p.ejecutar_rollback(pre_state, dev) == (True, True)
    assert dev.driver.ports[0].allowed_vlans == [10, 20, 30]


def test_ejecutar_rollback_paso_rechazado_es_intentado_y_fallido():
    dev = _device([_trunk([10, 20, 30, 40])])
    dev.driver.fail_on = lambda op_key, vars: op_key == "set_trunk_vlans_delta"
    p = Puerto(interface=_IFACE, allowed_vlans=[40], allowed_vlan_operation="add")
    pre_state = {"existed": True, "actual": _trunk([10, 20, 30])}

    assert p.ejecutar_rollback(pre_state, dev) == (True, False)


def _restore(snapshot: Puerto, ahora: "Puerto | None"):
    return snapshot.resolver_restore(_device([_trunk([10])]), ahora)[0]


def _snap() -> Puerto:
    return Puerto(interface=_IFACE, mode="trunk", access_vlan=1, allowed_vlans=[10, 20, 30])


def test_restore_sobre_un_trunk_manda_un_solo_paso_add_pvid_remove_no_set_trunk_mode():
    ahora = Puerto(interface=_IFACE, mode="trunk", access_vlan=5, allowed_vlans=[30, 40])
    pasos = _restore(_snap(), ahora)
    assert len(pasos) == 1
    op_key, _variant, vars = pasos[0]
    assert op_key == "set_trunk_config_delta"
    assert (vars["pvid"], vars["add"], vars["remove"]) == (1, [10, 20], [40])


def test_restore_sobre_un_trunk_con_pvid_igual_no_toca_el_pvid():
    ahora = Puerto(interface=_IFACE, mode="trunk", access_vlan=1, allowed_vlans=[10, 20])
    pasos = _restore(_snap(), ahora)
    assert [p[0] for p in pasos] == ["set_trunk_config_delta"]
    assert pasos[0][2]["pvid"] is None
    assert (pasos[0][2]["add"], pasos[0][2]["remove"]) == ([30], [])


def test_restore_solo_pvid_distinto_manda_solo_el_pvid():
    ahora = Puerto(interface=_IFACE, mode="trunk", access_vlan=5, allowed_vlans=[10, 20, 30])
    pasos = _restore(_snap(), ahora)
    assert [p[0] for p in pasos] == ["set_trunk_config_delta"]
    assert (pasos[0][2]["pvid"], pasos[0][2]["add"], pasos[0][2]["remove"]) == (1, [], [])


def test_restore_ya_restaurado_no_manda_nada():
    ahora = Puerto(interface=_IFACE, mode="trunk", access_vlan=1, allowed_vlans=[10, 20, 30])
    assert _restore(_snap(), ahora) == []


@pytest.mark.parametrize("ahora", [
    None,
    Puerto(interface=_IFACE, mode="access", access_vlan=10),
    Puerto(interface=_IFACE, mode="trunk", access_vlan=1, allowed_vlans=None),
])
def test_restore_sin_base_para_un_delta_cae_al_bloque_completo(ahora):
    pasos = _restore(_snap(), ahora)
    assert [p[0] for p in pasos] == ["set_trunk_mode"]


_PORT_VLAN_REAL = """\
Port                    Link Type    PVID  Trunk VLAN List                      Port Description
---------------------------------------------------------------------------------------------------------------
10GE6/0/43              trunk         531  144 381 531                          rou-dui2 XGE0/0/1
"""


def test_delta_sobre_lo_leido_por_el_parser_real_no_emite_vlans_fantasma():
    fila = parse_vrp_port_vlan(_PORT_VLAN_REAL)["10GE6/0/43"]
    assert fila.allowed_vlans == [144, 381, 531]
    actual = Puerto(interface="10GE6/0/43", mode="trunk", access_vlan=531, allowed_vlans=fila.allowed_vlans)
    p = Puerto(interface="10GE6/0/43", allowed_vlans=[144, 1, 2], allowed_vlan_operation="remove")
    _deseados, agregar, quitar = p._calcular_allowed_vlans(actual)
    assert (agregar, quitar) == ([], [144])


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakePuertoDriver()
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    return drv


def test_lote_que_falla_sin_tocar_nada_no_reporta_rollback_exitoso(admin_client, fake_driver):
    fake_driver.fail_on = lambda op_key, vars: op_key == "set_trunk_vlans_delta"
    dev = get_or_create_device("rb_batch_dev", site_name="Trunk Rollback Test Site")

    res = admin_client.post(
        f"/api/v1/devices/{dev.name}/ports/batch",
        json={"changes": [{"interface": _IFACE, "allowed_vlans": [40], "allowed_vlan_operation": "add"}]},
    )
    assert res.status_code == 202, res.text
    job = job_repository.get(res.json()["data"]["jobs"][0]["job_id"])
    assert job.status == "failed"
    assert job.rollback_performed in (False, None)
    assert job.rollback_success is None
