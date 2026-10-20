from __future__ import annotations

import pytest

from app.services.vendors.base import NO_CONFIRMADO, _confirmar_exito
from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor
from tests._device_helper import device_con_driver


def _res(stdout="", stderr="", rc=0, success=True):
    return {"rc": rc, "stdout": stdout, "stderr": stderr, "success": success}


def test_sin_patron_no_toca_el_resultado():
    r = _res(success=True)
    assert _confirmar_exito(r, None) is r


def test_el_patron_presente_confirma_y_no_distingue_mayusculas():
    r = _res("Building configuration...\n[ok]")
    assert _confirmar_exito(r, r"\[OK\]") is r


def test_el_patron_presente_borra_un_error_suelto():
    r = _res("Save the configuration successfully.\nError: Unrecognized command", "boom", rc=1, success=False)
    out = _confirmar_exito(r, "Save the configuration successfully")
    assert out["success"] is True and out["rc"] == 0 and out["stderr"] == ""


def test_exito_sin_el_texto_se_convierte_en_fallo_con_el_marcador():
    out = _confirmar_exito(_res(""), r"\[OK\]")
    assert out["success"] is False and out["rc"] == 1
    assert NO_CONFIRMADO in out["stderr"] and r"\[OK\]" in out["stderr"]


def test_un_fallo_sin_el_texto_queda_como_estaba():
    r = _res("% Invalid input", "x", rc=1, success=False)
    assert _confirmar_exito(r, r"\[OK\]") is r


class _Guion:
    def __init__(self, resultados):
        self.resultados = list(resultados)
        self.pasos: list = []

    def __call__(self, step, vars, device, password, *, op_label):
        self.pasos.append(step.get("block") or step.get("commands"))
        return self.resultados.pop(0)


def _correr(driver, resultados, vendor):
    guion = _Guion(resultados)
    driver._ejecutar_paso = guion
    dev = device_con_driver(driver, vendor=vendor)
    return driver.save_config(dev, "pw"), guion


CISCO_OK = "Building configuration...\nCompressed configuration from 3797 bytes to 2066 bytes[OK]"

CE_SAVE_Y = (
    "save\nWarning: The current configuration will be written to the device. Continue? [Y/N]:y\n"
    "Now saving the current configuration to the slot 17 \nInfo: Save the configuration successfully."
)
CE_SAVE_FORCE_RECHAZADO = "save force\r\nError: Invalid file name or file name extension ( *.cfg, *.zip, *.dat ).\r\n<HUAWEI>"
S57_SAVE_Y = (
    "<swhw01>save\nThe current configuration will be written to flash:/vrpcfg.cfg.\n"
    "Are you sure to continue?[Y/N]y\nNow saving the current configuration to the slot 0.\n"
    "Save the configuration successfully."
)


def test_huawei_save_y_que_confirma_es_un_solo_paso():
    for transcript in (CE_SAVE_Y, S57_SAVE_Y):
        r, g = _correr(HuaweiVendor(), [_res(transcript)], "huawei_vrp")
        assert r["success"] is True and g.pasos == [["save", "y"]]


def test_huawei_save_force_ya_no_es_la_primaria():
    todas = HuaweiVendor()._cargar_comandos()["save_config"]
    assert todas["primary"]["block"] == ["save", "y"]
    assert todas["alternatives"][0]["block"] == ["save force"]


def test_huawei_version_que_rechaza_el_y_prueba_save_force():
    r, g = _correr(HuaweiVendor(), [
        _res("save\nPlease input the file name(*.cfg,*.zip)[vrpcfg.zip]:y\nError: Invalid file name", rc=1, success=False),
        _res("save force\nSave the configuration successfully."),
    ], "huawei_vrp")
    assert r["success"] is True and g.pasos == [["save", "y"], ["save force"]]


def test_el_rechazo_real_de_save_force_del_ce12800_dispara_la_alternativa():
    import re
    for op in (HuaweiVendor()._cargar_comandos()["save_config"],):
        gatillo = op["alternatives"][0]["triggered_by_error"]
        assert re.search(gatillo, CE_SAVE_FORCE_RECHAZADO)


def test_huawei_rc_cero_sin_confirmacion_tambien_prueba_la_alternativa():
    r, g = _correr(HuaweiVendor(), [
        _res("<sw>save\n"),
        _res("save force\nSave the configuration successfully."),
    ], "huawei_vrp")
    assert r["success"] is True and len(g.pasos) == 2


def test_huawei_y_de_mas_no_es_un_fallo_si_el_equipo_confirmo():
    r, g = _correr(HuaweiVendor(), [
        _res("save\nSave the configuration successfully.\ny\nError: Unrecognized command", "err", rc=1, success=False),
    ], "huawei_vrp")
    assert r["success"] is True and r["rc"] == 0 and len(g.pasos) == 1


def test_huawei_si_ninguna_variante_confirma_devuelve_el_fallo_con_el_transcript():
    r, g = _correr(HuaweiVendor(), [
        _res("Error: Unrecognized command", rc=1, success=False),
        _res("Please input the file name(*.cfg,*.zip)[vrpcfg.zip]:\nError: The file name is invalid"),
    ], "huawei_vrp")
    assert r["success"] is False and NO_CONFIRMADO in r["stderr"]
    assert "Please input the file name" in r["stdout"]


def test_cisco_write_que_confirma_es_un_solo_paso():
    r, g = _correr(CiscoVendor(), [_res(CISCO_OK)], "cisco_ios")
    assert r["success"] is True and g.pasos == [["write"]]


def test_cisco_write_no_reconocido_cae_a_write_memory():
    r, g = _correr(CiscoVendor(), [
        _res("% Invalid input detected at '^' marker.", rc=1, success=False),
        _res(CISCO_OK),
    ], "cisco_ios")
    assert r["success"] is True and g.pasos == [["write"], ["write memory"]]


def test_cisco_rc_cero_sin_ok_no_se_da_por_guardado():
    r, g = _correr(CiscoVendor(), [_res(""), _res("")], "cisco_ios")
    assert r["success"] is False and NO_CONFIRMADO in r["stderr"]
    assert g.pasos == [["write"], ["write memory"]]


def test_cisco_no_usa_copy_running_config():
    todas = CiscoVendor()._cargar_comandos()["save_config"]
    pasos = [todas["primary"]] + todas["alternatives"]
    assert not any("copy" in c for p in pasos for c in p["commands"])


def test_el_success_pattern_de_cada_vendor_esta_en_el_yaml():
    assert CiscoVendor()._cargar_comandos()["save_config"]["success_pattern"] == r"\[OK\]"
    assert HuaweiVendor()._cargar_comandos()["save_config"]["success_pattern"] == "Save the configuration successfully"
