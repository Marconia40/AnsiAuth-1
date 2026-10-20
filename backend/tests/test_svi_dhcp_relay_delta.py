from __future__ import annotations

import pytest

from app.models.svi import SVI
from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor
from tests._device_helper import device_con_driver as _device


class _Driver:
    def __init__(self, servers=None, *, acl_in=None, acl_out=None):
        self.servers = list(servers or [])
        self.acl = {"in": acl_in, "out": acl_out}
        self.pasos: list = []
        self.lecturas = 0

    def resolver_set_svi_dhcp_relay_delta(
        self, vlan_id, add, remove, final, layout=None, indices_previos=None,
    ):
        return ("delta", None, {"vlan_id": vlan_id, "add": list(add), "remove": list(remove), "final": list(final)})

    def resolver_set_svi_dhcp_relay(self, vlan_id, servers):
        return ("full", None, {"vlan_id": vlan_id, "servers": list(servers)})

    def resolver_set_svi_acl(self, vlan_id, direccion, acl, current_acl_name=None):
        return ("acl", None, {"vlan_id": vlan_id, "dir": direccion, "acl": acl, "current": current_acl_name})

    def aplicar_paso(self, op_key, variant, vars, device, password):
        self.pasos.append((op_key, vars))
        if op_key == "delta":
            self.servers = [s for s in self.servers if s not in vars["remove"]] + [
                s for s in vars["add"] if s not in self.servers
            ]
        elif op_key == "full":
            self.servers = list(vars["servers"])
        elif op_key == "acl":
            self.acl[vars["dir"]] = vars["acl"] or None
        return {"rc": 0}

    def get_svis(self, device, password):
        self.lecturas += 1
        return [SVI(
            vlan_id=50, device="swcs01", ipv4_address="10.0.0.1/24",
            dhcp_relay_servers=list(self.servers) or None,
            acl_in=self.acl["in"], acl_out=self.acl["out"],
        )]


def _svi(**k) -> SVI:
    return SVI(vlan_id=50, device="swcs01", **k)


def _pre(servers=None, **k) -> dict:
    return {"existed": True, "actual": SVI(
        vlan_id=50, device="swcs01", ipv4_address="10.0.0.1/24",
        dhcp_relay_servers=list(servers) if servers else None, **k,
    )}


def _ahora(servers=None, **k) -> SVI:
    return SVI(vlan_id=50, device="swcs01", ipv4_address="10.0.0.1/24",
               dhcp_relay_servers=list(servers) if servers else None, **k)


def _render_cisco(paso):
    op_key, variant, vars = paso
    step = CiscoVendor()._cargar_comandos()[op_key]["primary"]
    return CiscoVendor()._renderizar_paso(step, vars)


def _lineas_cisco(add, remove):
    paso = CiscoVendor().resolver_set_svi_dhcp_relay_delta(50, add, remove, [])
    return _render_cisco(paso)


def test_cisco_delta_solo_agrega_sin_borrar_los_demas():
    r = _lineas_cisco(["10.9.9.9"], [])
    assert r["parents"] == "interface Vlan50"
    assert r["lines"] == ["ip helper-address 10.9.9.9"]
    assert r["match"] == "none"
    assert "no ip helper-address" not in r["lines"]


def test_cisco_delta_solo_quita_ese_server():
    r = _lineas_cisco([], ["10.9.9.9"])
    assert r["lines"] == ["no ip helper-address 10.9.9.9"]


def test_cisco_delta_agrega_primero_y_quita_despues():
    r = _lineas_cisco(["10.1.1.1", "10.2.2.2"], ["10.9.9.9"])
    assert r["lines"] == [
        "ip helper-address 10.1.1.1", "ip helper-address 10.2.2.2", "no ip helper-address 10.9.9.9",
    ]


def test_cisco_delta_nunca_manda_el_borrado_total():
    for add, remove in ((["1.1.1.1"], []), ([], ["1.1.1.1"]), (["1.1.1.1"], ["2.2.2.2"])):
        assert "no ip helper-address" not in _lineas_cisco(add, remove)["lines"]


def test_cisco_delta_exige_algo_que_hacer():
    with pytest.raises(ValueError):
        CiscoVendor().resolver_set_svi_dhcp_relay_delta(50, [], [], [])


def test_huawei_delega_en_el_full_replace_con_la_lista_final():
    paso = HuaweiVendor().resolver_set_svi_dhcp_relay_delta(50, ["1.1.1.1"], [], ["2.2.2.2", "1.1.1.1"])
    assert paso == HuaweiVendor().resolver_set_svi_dhcp_relay(50, ["2.2.2.2", "1.1.1.1"])
    assert paso[0] == "set_svi_dhcp_relay"


def test_apply_add_manda_delta_con_la_lista_final():
    dev = _device(_Driver())
    paso = _svi(dhcp_relay_add="10.9.9.9").resolver_paso(dev, _ahora(["10.1.1.1"]))
    assert paso == ("delta", None, {"vlan_id": 50, "add": ["10.9.9.9"], "remove": [], "final": ["10.1.1.1", "10.9.9.9"]})


def test_apply_remove_manda_delta_con_la_lista_final():
    dev = _device(_Driver())
    paso = _svi(dhcp_relay_remove="10.1.1.1").resolver_paso(dev, _ahora(["10.1.1.1", "10.2.2.2"]))
    assert paso == ("delta", None, {"vlan_id": 50, "add": [], "remove": ["10.1.1.1"], "final": ["10.2.2.2"]})


def test_apply_add_de_uno_que_ya_esta_y_remove_de_uno_que_no_esta_son_noop():
    dev = _device(_Driver())
    assert _svi(dhcp_relay_add="10.1.1.1").resolver_paso(dev, _ahora(["10.1.1.1"])) is None
    assert _svi(dhcp_relay_remove="10.7.7.7").resolver_paso(dev, _ahora(["10.1.1.1"])) is None


@pytest.mark.parametrize("ahora, esperado", [
    (["10.1.1.1", "10.9.9.9", "10.3.3.3"], ("delta", {"vlan_id": 50, "add": [], "remove": ["10.9.9.9"], "final": ["10.1.1.1", "10.3.3.3"]})),
    (["10.1.1.1", "10.9.9.9"], ("delta", {"vlan_id": 50, "add": [], "remove": ["10.9.9.9"], "final": ["10.1.1.1"]})),
    (["10.1.1.1"], None),
])
def test_rollback_add_con_lectura_fresca(ahora, esperado):
    dev = _device(_Driver())
    pasos, verificar = _svi(dhcp_relay_add="10.9.9.9").resolver_rollback(_pre(["10.1.1.1"]), dev, _ahora(ahora))
    if esperado is None:
        assert pasos == [] and verificar is None
    else:
        assert pasos == [(esperado[0], None, esperado[1])]


@pytest.mark.parametrize("ahora, esperado", [
    (["10.2.2.2", "10.4.4.4"], ("delta", {"vlan_id": 50, "add": ["10.1.1.1"], "remove": [], "final": ["10.2.2.2", "10.4.4.4", "10.1.1.1"]})),
    (["10.1.1.1", "10.2.2.2"], None),
])
def test_rollback_remove_con_lectura_fresca(ahora, esperado):
    dev = _device(_Driver())
    pasos, _ = _svi(dhcp_relay_remove="10.1.1.1").resolver_rollback(
        _pre(["10.1.1.1", "10.2.2.2"]), dev, _ahora(ahora),
    )
    if esperado is None:
        assert pasos == []
    else:
        assert pasos == [(esperado[0], None, esperado[1])]


def test_rollback_no_revierte_un_noop_del_apply():
    dev = _device(_Driver())
    assert _svi(dhcp_relay_add="10.1.1.1").resolver_rollback(_pre(["10.1.1.1"]), dev, _ahora(["10.1.1.1"]))[0] == []
    assert _svi(dhcp_relay_remove="10.7.7.7").resolver_rollback(_pre(["10.1.1.1"]), dev, _ahora(["10.1.1.1"]))[0] == []


def test_rollback_sin_lectura_fresca_es_incondicional_con_la_lista_previa():
    dev = _device(_Driver())
    pasos, _ = _svi(dhcp_relay_add="10.9.9.9").resolver_rollback(_pre(["10.1.1.1"]), dev, None)
    assert pasos == [("delta", None, {"vlan_id": 50, "add": [], "remove": ["10.9.9.9"], "final": ["10.1.1.1"]})]
    pasos, _ = _svi(dhcp_relay_remove="10.1.1.1").resolver_rollback(_pre(["10.1.1.1", "10.2.2.2"]), dev, None)
    assert pasos == [("delta", None, {"vlan_id": 50, "add": ["10.1.1.1"], "remove": [], "final": ["10.1.1.1", "10.2.2.2"]})]


def test_verificador_mira_solo_el_server_del_cambio_no_la_lista_completa():
    dev = _device(_Driver())
    _, verif_add = _svi(dhcp_relay_add="10.9.9.9").resolver_rollback(_pre(["10.1.1.1"]), dev, _ahora(["10.1.1.1", "10.9.9.9"]))
    assert verif_add(_ahora(["10.1.1.1", "10.6.6.6"])) is True
    assert verif_add(_ahora(["10.1.1.1", "10.9.9.9"])) is False
    assert verif_add(None) is False
    _, verif_rm = _svi(dhcp_relay_remove="10.1.1.1").resolver_rollback(_pre(["10.1.1.1"]), dev, _ahora([]))
    assert verif_rm(_ahora(["10.1.1.1", "10.6.6.6"])) is True
    assert verif_rm(_ahora(["10.6.6.6"])) is False


def test_single_add_quita_solo_ese_server_y_deja_el_del_tercero():
    drv = _Driver(["10.1.1.1", "10.9.9.9", "10.3.3.3"])
    dev = _device(drv)
    hecho, ok = _svi(dhcp_relay_add="10.9.9.9").ejecutar_rollback(_pre(["10.1.1.1"]), dev)
    assert (hecho, ok) == (True, True)
    assert drv.servers == ["10.1.1.1", "10.3.3.3"]
    assert [p[0] for p in drv.pasos] == ["delta"]


def test_single_add_que_nunca_se_aplico_no_manda_nada():
    drv = _Driver(["10.1.1.1"])
    dev = _device(drv)
    hecho, ok = _svi(dhcp_relay_add="10.9.9.9").ejecutar_rollback(_pre(["10.1.1.1"]), dev)
    assert (hecho, ok) == (False, None)
    assert drv.pasos == []


def test_single_remove_vuelve_a_agregar_solo_ese():
    drv = _Driver(["10.2.2.2", "10.4.4.4"])
    dev = _device(drv)
    hecho, ok = _svi(dhcp_relay_remove="10.1.1.1").ejecutar_rollback(_pre(["10.1.1.1", "10.2.2.2"]), dev)
    assert (hecho, ok) == (True, True)
    assert drv.servers == ["10.2.2.2", "10.4.4.4", "10.1.1.1"]


def test_restore_con_lectura_fresca_es_incremental():
    dev = _device(_Driver())
    snap = _svi(dhcp_relay_servers=["10.1.1.1", "10.2.2.2"])
    pasos, _ = snap.resolver_restore(dev, _ahora(["10.2.2.2", "10.5.5.5"]))
    assert pasos == [("delta", None, {
        "vlan_id": 50, "add": ["10.1.1.1"], "remove": ["10.5.5.5"], "final": ["10.1.1.1", "10.2.2.2"],
    })]


def test_restore_sin_lectura_fresca_cae_al_full_replace():
    dev = _device(_Driver())
    snap = _svi(dhcp_relay_servers=["10.1.1.1"])
    pasos, _ = snap.resolver_restore(dev, None)
    assert pasos == [("full", None, {"vlan_id": 50, "servers": ["10.1.1.1"]})]


def test_restore_no_manda_nada_si_ya_coincide():
    dev = _device(_Driver())
    snap = _svi(dhcp_relay_servers=["10.1.1.1"])
    assert snap.resolver_restore(dev, _ahora(["10.1.1.1"]))[0] == []


@pytest.mark.parametrize("campo", ["acl_in", "acl_out"])
class TestAclCompareAndSwap:
    def test_revierte_si_la_acl_actual_es_la_que_puso_el_cambio(self, campo):
        dev = _device(_Driver())
        pasos, verif = _svi(**{campo: "NUEVA"}).resolver_rollback(
            _pre(**{campo: "VIEJA"}), dev, _ahora(**{campo: "NUEVA"}),
        )
        d = "in" if campo == "acl_in" else "out"
        assert pasos == [("acl", None, {"vlan_id": 50, "dir": d, "acl": "VIEJA", "current": "NUEVA"})]
        assert verif(_ahora(**{campo: "VIEJA"})) is True
        assert verif(_ahora(**{campo: "NUEVA"})) is False

    def test_no_pisa_la_acl_que_cambio_un_tercero_despues(self, campo):
        dev = _device(_Driver())
        pasos, verif = _svi(**{campo: "NUEVA"}).resolver_rollback(
            _pre(**{campo: "VIEJA"}), dev, _ahora(**{campo: "DE-UN-TERCERO"}),
        )
        assert pasos == [] and verif is None

    def test_nada_que_hacer_si_el_apply_nunca_llego_al_equipo(self, campo):
        dev = _device(_Driver())
        assert _svi(**{campo: "NUEVA"}).resolver_rollback(
            _pre(**{campo: "VIEJA"}), dev, _ahora(**{campo: "VIEJA"}),
        )[0] == []
        assert _svi(**{campo: "NUEVA"}).resolver_rollback(_pre(), dev, _ahora())[0] == []

    def test_clear_pedido_se_revierte_si_ahora_no_hay_nada_atado(self, campo):
        dev = _device(_Driver())
        pasos, _ = _svi(**{campo: ""}).resolver_rollback(
            _pre(**{campo: "VIEJA"}), dev, _ahora(),
        )
        assert len(pasos) == 1 and pasos[0][2]["acl"] == "VIEJA" and pasos[0][2]["current"] is None

    def test_clear_pedido_no_pisa_una_acl_de_un_tercero(self, campo):
        dev = _device(_Driver())
        assert _svi(**{campo: ""}).resolver_rollback(
            _pre(**{campo: "VIEJA"}), dev, _ahora(**{campo: "DE-UN-TERCERO"}),
        )[0] == []

    def test_sin_lectura_fresca_no_revierte(self, campo):
        dev = _device(_Driver())
        assert _svi(**{campo: "NUEVA"}).resolver_rollback(_pre(**{campo: "VIEJA"}), dev, None)[0] == []

    def test_single_revierte_solo_si_sigue_la_del_cambio(self, campo):
        d = "in" if campo == "acl_in" else "out"
        drv = _Driver(**{campo: "NUEVA"})
        assert _svi(**{campo: "NUEVA"}).ejecutar_rollback(_pre(**{campo: "VIEJA"}), _device(drv)) == (True, True)
        assert drv.acl[d] == "VIEJA"

        drv = _Driver(**{campo: "DE-UN-TERCERO"})
        assert _svi(**{campo: "NUEVA"}).ejecutar_rollback(_pre(**{campo: "VIEJA"}), _device(drv)) == (False, None)
        assert drv.pasos == [] and drv.acl[d] == "DE-UN-TERCERO"
