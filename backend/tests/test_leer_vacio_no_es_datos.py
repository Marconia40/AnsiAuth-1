from __future__ import annotations

import pytest

from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor
from tests._device_helper import device_con_driver


def _leer(driver_cls, resultado, *, partial_ok):
    drv = driver_cls()
    drv._ejecutar = lambda extravars, device, password: resultado
    dev = device_con_driver(drv)
    return drv._leer(["a", "b", "c"], dev, "pw", partial_ok=partial_ok)


@pytest.mark.parametrize("driver_cls", [CiscoVendor, HuaweiVendor])
def test_todo_vacio_con_rc_cero_en_lectura_tolerante_es_error(driver_cls):
    with pytest.raises(RuntimeError, match="every command returned empty output"):
        _leer(driver_cls, {"rc": 0, "stdout": "", "stderr": "", "stdouts": ["", "  ", "\n"]}, partial_ok=True)


@pytest.mark.parametrize("driver_cls", [CiscoVendor, HuaweiVendor])
def test_si_al_menos_un_comando_devolvio_algo_se_entrega_todo(driver_cls):
    stdouts = ["Port Name Status", "", ""]
    assert _leer(driver_cls, {"rc": 0, "stdout": "", "stderr": "", "stdouts": stdouts}, partial_ok=True) == stdouts


def test_la_lectura_estricta_no_cambia():
    stdouts = ["", ""]
    assert _leer(CiscoVendor, {"rc": 0, "stdout": "", "stderr": "", "stdouts": stdouts}, partial_ok=False) == stdouts


def test_sin_salidas_sigue_fallando_como_antes():
    with pytest.raises(RuntimeError, match="no command output returned"):
        _leer(CiscoVendor, {"rc": 0, "stdout": "", "stderr": "", "stdouts": []}, partial_ok=True)


def test_un_solo_comando_vacio_es_legitimo():
    drv = CiscoVendor()
    drv._ejecutar = lambda extravars, device, password: {"rc": 0, "stdout": "", "stderr": "", "stdouts": [""]}
    assert drv._leer(["show logging | include x"], device_con_driver(drv), "pw", partial_ok=True) == [""]
