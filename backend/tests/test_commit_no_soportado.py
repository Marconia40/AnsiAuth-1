from __future__ import annotations

from types import SimpleNamespace

from app.services.vendors.base import _solo_rechazo_commit
from app.services.vendors.huawei.driver import HuaweiVendor

_COMMIT_RECHAZADO = (
    "[~swhw02-GigabitEthernet0/0/43]port trunk allow-pass vlan 600\r\n"
    "[~swhw02-GigabitEthernet0/0/43]commit\r\n"
    "                               ^\r\n"
    "Error: Unrecognized command found at '^' position.\r\n"
    "[~swhw02-GigabitEthernet0/0/43]"
)

_INTERFAZ_RECHAZADA = (
    "[~swhw02]interface GE0/0/43\r\n"
    "                  ^\r\n"
    "Error: Wrong parameter found at '^' position.\r\n"
)

_DEVICE = SimpleNamespace(name="swhw02", vendor="huawei_vrp")
_VARS = {
    "interface": "GE0/0/43",
    "interface_full": "GigabitEthernet0/0/43",
    "allowed_vlans": "144 381 531 600",
}


def _driver_con(resultados: list[dict]):
    driver = HuaweiVendor()
    enviados: list[dict] = []

    def _ejecutar(extravars, device, password):
        enviados.append(extravars)
        return resultados[len(enviados) - 1]

    driver._ejecutar = _ejecutar  # type: ignore[method-assign]
    return driver, enviados


def test_solo_rechazo_de_commit_es_cosmetico():
    assert _solo_rechazo_commit(_COMMIT_RECHAZADO, "huawei_vrp") is True


def test_commit_mas_un_error_real_no_es_cosmetico():
    assert _solo_rechazo_commit(_INTERFAZ_RECHAZADA + _COMMIT_RECHAZADO, "huawei_vrp") is False


def test_sin_rechazo_de_commit_no_aplica():
    assert _solo_rechazo_commit(_INTERFAZ_RECHAZADA, "huawei_vrp") is False
    assert _solo_rechazo_commit("", "huawei_vrp") is False


def test_texto_de_ansible_con_crlf_literal_tambien_se_detecta():
    literal = "Task failed: b'" + _COMMIT_RECHAZADO.replace("\r\n", "\\r\\n") + "'"
    normalizado = literal.replace("\\r\\n", "\r\n")
    assert _solo_rechazo_commit(normalizado, "huawei_vrp") is True


def test_aplicar_desde_template_solo_commit_rechazado_es_exito_sin_reenviar():
    driver, enviados = _driver_con([{"rc": 1, "stdout": _COMMIT_RECHAZADO, "stderr": ""}])
    resultado = driver._aplicar_desde_template("set_trunk_allowed_vlans", _VARS, _DEVICE, "pw")
    assert resultado["success"] is True
    assert resultado["rc"] == 0
    assert len(enviados) == 1


def test_aplicar_desde_template_commit_mas_error_real_sigue_reintentando():
    driver, enviados = _driver_con([
        {"rc": 1, "stdout": _INTERFAZ_RECHAZADA + _COMMIT_RECHAZADO, "stderr": ""},
        {"rc": 0, "stdout": "ok", "stderr": ""},
    ])
    resultado = driver._aplicar_desde_template("set_trunk_allowed_vlans", _VARS, _DEVICE, "pw")
    assert resultado["success"] is True
    assert len(enviados) == 2
    assert "interface GigabitEthernet0/0/43" in enviados[1]["command_block"]


def test_aplicar_desde_template_error_de_interfaz_solo_sigue_reintentando():
    driver, enviados = _driver_con([
        {"rc": 1, "stdout": _INTERFAZ_RECHAZADA, "stderr": ""},
        {"rc": 0, "stdout": "ok", "stderr": ""},
    ])
    resultado = driver._aplicar_desde_template("set_trunk_allowed_vlans", _VARS, _DEVICE, "pw")
    assert resultado["success"] is True
    assert len(enviados) == 2


_PASOS = [("set_trunk_allowed_vlans", None, _VARS)]


def test_aplicar_lote_solo_commit_rechazado_es_exito_sin_reenviar():
    driver, enviados = _driver_con([{"rc": 1, "stdout": _COMMIT_RECHAZADO, "stderr": ""}])
    resultado = driver.aplicar_lote(_PASOS, _DEVICE, "pw")
    assert resultado["success"] is True
    assert len(enviados) == 1


def test_aplicar_lote_commit_mas_error_real_sigue_reintentando():
    driver, enviados = _driver_con([
        {"rc": 1, "stdout": _INTERFAZ_RECHAZADA + _COMMIT_RECHAZADO, "stderr": ""},
        {"rc": 0, "stdout": "ok", "stderr": ""},
    ])
    resultado = driver.aplicar_lote(_PASOS, _DEVICE, "pw")
    assert resultado["success"] is True
    assert len(enviados) == 2
