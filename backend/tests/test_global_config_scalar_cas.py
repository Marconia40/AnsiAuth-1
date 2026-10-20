from __future__ import annotations

import pytest

from app.models.global_config import GlobalConfig
from tests._device_helper import device_con_driver as _device

DEV = "swcs01"


class _Driver:
    def __init__(self, hostname=None, version=None, community=None, lectura_falla=False):
        self.hostname, self.version, self.community = hostname, version, community
        self.lectura_falla = lectura_falla
        self.calls: list = []

    def get_global_config(self, device, password):
        if self.lectura_falla:
            raise RuntimeError("sin acceso")
        return GlobalConfig(
            device=DEV, hostname=self.hostname, snmp_version=self.version, snmp_community=self.community,
        )

    def set_hostname(self, name, device, password):
        self.calls.append(("set_hostname", name)); self.hostname = name
        return {"rc": 0}

    def set_snmp(self, cambios, device, password):
        self.calls.append(("set_snmp", dict(cambios)))
        if "version" in cambios:
            self.version = cambios["version"]
        if "community" in cambios:
            self.community = cambios["community"]
        return {"rc": 0}


def _pre(**k) -> dict:
    return {"existed": True, "actual": GlobalConfig(device=DEV, **k)}


def _rollback(cambio: GlobalConfig, pre: dict, **estado):
    drv = _Driver(**estado)
    return cambio.ejecutar_rollback(pre, _device(drv)), drv


def _hostname(nuevo="new"):
    return GlobalConfig(device=DEV, hostname=nuevo)


def test_hostname_se_revierte_si_sigue_el_que_puso_el_cambio():
    res, drv = _rollback(_hostname(), _pre(hostname="old"), hostname="new")
    assert res == (True, True)
    assert drv.calls == [("set_hostname", "old")] and drv.hostname == "old"


def test_hostname_ignora_mayusculas_al_comparar():
    res, drv = _rollback(_hostname("new"), _pre(hostname="old"), hostname="NEW")
    assert res[0] is True and drv.calls == [("set_hostname", "old")]


@pytest.mark.parametrize("actual", ["old", "third-party"])
def test_hostname_no_toca_nada_si_ya_es_el_previo_o_lo_cambio_un_tercero(actual):
    res, drv = _rollback(_hostname(), _pre(hostname="old"), hostname=actual)
    assert res == (False, None) and drv.calls == [] and drv.hostname == actual


def test_hostname_ilegible_o_sin_lectura_se_revierte_como_antes():
    res, drv = _rollback(_hostname(), _pre(hostname="old"), hostname=None)
    assert res[0] is True and drv.calls == [("set_hostname", "old")]
    res, drv = _rollback(_hostname(), _pre(hostname="old"), hostname="new", lectura_falla=True)
    assert res[0] is True and drv.calls == [("set_hostname", "old")]


def _snmp(**cfg):
    return GlobalConfig(device=DEV, snmp_config=cfg)


PRE_SNMP = dict(snmp_version="2c", snmp_community="oldc")


def test_snmp_revierte_ambos_si_siguen_siendo_los_del_cambio():
    res, drv = _rollback(
        _snmp(version="3", community="newc"), _pre(**PRE_SNMP), version="3", community="newc",
    )
    assert res == (True, True)
    assert drv.calls == [("set_snmp", {"version": "2c", "community": "oldc"})]


def test_snmp_omite_el_sub_campo_que_cambio_un_tercero_y_verifica_solo_lo_revertido():
    res, drv = _rollback(
        _snmp(version="3", community="newc"), _pre(**PRE_SNMP), version="3", community="third-party",
    )
    assert drv.calls == [("set_snmp", {"version": "2c"})]
    assert res == (True, True)
    assert drv.community == "third-party"


def test_snmp_sin_nada_que_revertir_no_manda_nada():
    for estado in (dict(version="2c", community="oldc"), dict(version="1", community="third-party")):
        res, drv = _rollback(_snmp(version="3", community="newc"), _pre(**PRE_SNMP), **estado)
        assert res == (False, None) and drv.calls == []


def test_snmp_community_ilegible_como_en_huawei_se_revierte_igual():
    res, drv = _rollback(
        _snmp(version="3", community="newc"), _pre(**PRE_SNMP), version="3", community=None,
    )
    assert drv.calls == [("set_snmp", {"version": "2c", "community": "oldc"})]
    assert res[0] is True


def test_snmp_sin_lectura_fresca_se_revierte_como_antes():
    res, drv = _rollback(
        _snmp(version="3", community="newc"), _pre(**PRE_SNMP), version="3", community="newc",
        lectura_falla=True,
    )
    assert drv.calls == [("set_snmp", {"version": "2c", "community": "oldc"})]
    assert res[0] is True


def test_snmp_solo_pedida_la_version_no_toca_la_community():
    res, drv = _rollback(_snmp(version="3"), _pre(**PRE_SNMP), version="3", community="lo-que-sea")
    assert drv.calls == [("set_snmp", {"version": "2c"})]
