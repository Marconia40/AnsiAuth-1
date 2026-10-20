from __future__ import annotations

import logging
from dataclasses import asdict

import pytest

from app.composition import job_repository, plugin_registry
from app.models.global_config import GlobalConfig
from app.models.port import Puerto
from app.models.save_config import GuardarConfig
from app.models.svi import SVI
from app.models.vlan import VLAN
from tests._device_helper import device_con_driver
from tests._puerto_fakes import FakePuertoDriver, get_or_create_device


class _Driver:
    def __init__(self, resultado=None):
        self.resultado = resultado or {"rc": 0, "stdout": "ok", "stderr": "", "success": True}
        self.guardados = 0

    def save_config(self, device, password):
        self.guardados += 1
        return dict(self.resultado)

    def get_vlans(self, *a, **k):
        raise AssertionError("guardar no debe leer el equipo")

    list_ports = get_svis = get_global_config = get_vlans


def test_aplicar_guarda_y_marca_la_accion():
    drv = _Driver(); dev = device_con_driver(drv)
    r = GuardarConfig(device="swcs01").aplicar(dev)
    assert r["accion"] == "guardar_configuracion" and r["success"] is True and drv.guardados == 1


def test_un_fallo_del_driver_llega_tal_cual():
    drv = _Driver({"rc": 1, "stdout": "x", "stderr": "no confirmo", "success": False})
    r = GuardarConfig().aplicar(device_con_driver(drv))
    assert r["success"] is False and r["accion"] == "guardar_configuracion"


def test_reconciliar_no_abre_ninguna_conexion():
    drv = _Driver()
    assert GuardarConfig().reconciliar(device_con_driver(drv)) == {"existed": True, "actual": None}


def test_no_hay_nada_que_revertir():
    assert GuardarConfig().ejecutar_rollback({"existed": True, "actual": None}, device_con_driver(_Driver())) == (False, None)


def test_contrato_basico():
    g = GuardarConfig(device="swcs01")
    g.validar()
    assert g.repositorio() == "save_config"
    assert g.resolver_paso(device_con_driver(_Driver()), None) == ("save_config", None, {})
    assert "swcs01" in g.resumen_intento()
    assert GuardarConfig(**asdict(g)) == g


def test_solo_guardar_y_global_config_evitan_persistirse_en_la_cache():
    assert GuardarConfig.PERSISTE_EN_CACHE is False and GlobalConfig.PERSISTE_EN_CACHE is False
    for tipo in (Puerto, SVI, VLAN):
        assert getattr(tipo, "PERSISTE_EN_CACHE", True) is True


def test_el_worker_conoce_el_tipo():
    import inspect
    from app import tasks
    assert '"save_config": GuardarConfig' in inspect.getsource(tasks.ejecutar_task)


_DEVICE = "save_cfg_dev"


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakePuertoDriver()
    monkeypatch.setitem(plugin_registry._vendors, "cisco_ios", drv)
    monkeypatch.setitem(plugin_registry._vendors, "huawei_vrp", drv)
    return drv


@pytest.fixture
def device(fake_driver):
    return get_or_create_device(_DEVICE, site_name="Save Config Test Site")


def _url(name=_DEVICE):
    return f"/api/v1/devices/{name}/save-config"


def test_rechaza_sin_autenticar(unauth_client, device):
    assert unauth_client.post(_url()).status_code == 401


def test_rechaza_observer(observer_client, device):
    assert observer_client.post(_url()).status_code == 403


def test_operator_puede(operator_client, device):
    res = operator_client.post(_url())
    assert res.status_code == 202, res.text
    data = res.json()["data"]
    assert data["group_job_id"] and data["jobs"][0]["device"] == _DEVICE


def test_equipo_inexistente_da_404(admin_client, device):
    assert admin_client.post(_url("no_existe_xyz")).status_code == 404


class _Capturador(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG); self.mensajes = []

    def emit(self, record):
        self.mensajes.append(record.getMessage())


def test_el_job_completa_registra_la_accion_y_no_intenta_cachear_el_recurso(admin_client, device, fake_driver):
    from app.services import orquestador as orq_module
    captura = _Capturador()
    orq_module.logger.addHandler(captura)
    nivel, deshabilitado = orq_module.logger.level, orq_module.logger.disabled
    orq_module.logger.setLevel(logging.DEBUG); orq_module.logger.disabled = False
    try:
        res = admin_client.post(_url())
        assert res.status_code == 202
        job = job_repository.get(res.json()["data"]["jobs"][0]["job_id"])
    finally:
        orq_module.logger.removeHandler(captura)
        orq_module.logger.setLevel(nivel); orq_module.logger.disabled = deshabilitado
    assert job.status == "completed"
    assert job.operation == "save_config"
    assert job.result["accion"] == "guardar_configuracion"
    assert job.rollback_performed is False
    assert not any("Tracking write failed" in m for m in captura.mensajes)


def test_si_el_equipo_no_confirma_el_job_falla_sin_rollback(admin_client, device, fake_driver, monkeypatch):
    monkeypatch.setattr(
        fake_driver, "save_config",
        lambda *a, **k: {"rc": 1, "stdout": "", "stderr": "The device did not confirm the operation", "success": False},
    )
    res = admin_client.post(_url())
    job = job_repository.get(res.json()["data"]["jobs"][0]["job_id"])
    assert job.status == "failed"
    assert job.rollback_performed is False
