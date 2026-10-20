from __future__ import annotations

import contextlib

import pytest

import app.services.orquestador as orquestador_module
from app.models.device import Device
from app.models.job import Job
from app.services.vendors.base import (
    PATRONES_SIN_CONEXION,
    AlcanceEscritura,
    _no_conecto,
    rastrear_escrituras,
    registrar_intento_escritura,
)
from app.services.orquestador import Orquestador
from app.services.vendors.cisco.driver import CiscoVendor


SIN_CONEXION = {"rc": 1, "stdout": "", "stderr": "Unable to connect to port 22 on 192.0.2.50"}
RECHAZADA = {"rc": 1, "stdout": "", "stderr": "ssh: connect to host 192.0.2.50 port 22: Connection refused"}
NEGOCIACION = {"rc": 255, "stdout": "", "stderr": "Unable to negotiate with 192.0.2.50 port 22: no matching cipher found. Their offer: aes128-cbc"}
TIMEOUT = {"rc": 1, "stdout": "", "stderr": "ssh command timed out after 60s"}
CANAL_CERRADO = {"rc": 1, "stdout": "", "stderr": "Channel closed"}
RECHAZO_DEL_EQUIPO = {"rc": 1, "stdout": "% Invalid input detected", "stderr": ""}
CON_SALIDA_PARCIAL = {**SIN_CONEXION, "stdouts": ["interface Gi0/1 done"]}
OK = {"rc": 0, "stdout": "", "stderr": ""}


class TestAlcanceEscritura:
    @pytest.mark.parametrize("resultado", [SIN_CONEXION, RECHAZADA, NEGOCIACION])
    def test_conexion_que_nunca_se_abrio_cuenta_como_sin_conexion(self, resultado):
        a = AlcanceEscritura()
        a.registrar(resultado)
        assert a.nunca_llego

    @pytest.mark.parametrize(
        "resultado", [TIMEOUT, CANAL_CERRADO, RECHAZO_DEL_EQUIPO, CON_SALIDA_PARCIAL, OK],
    )
    def test_cualquier_otra_cosa_asume_que_pudo_escribir(self, resultado):
        a = AlcanceEscritura()
        a.registrar(resultado)
        assert not a.nunca_llego

    def test_sin_intentos_no_se_asume_nada(self):
        assert not AlcanceEscritura().nunca_llego

    def test_un_intento_que_si_llego_anula_los_demas(self):
        a = AlcanceEscritura()
        a.registrar(RECHAZO_DEL_EQUIPO)
        a.registrar(SIN_CONEXION)
        assert not a.nunca_llego

    def test_varios_intentos_todos_sin_conexion(self):
        a = AlcanceEscritura()
        for _ in range(3):
            a.registrar(SIN_CONEXION)
        assert a.nunca_llego

    def test_una_excepcion_de_conexion_cuenta_igual(self):
        a = AlcanceEscritura()
        a.registrar(error=ConnectionRefusedError("[Errno 111] Connection refused"))
        assert a.nunca_llego

    def test_una_excepcion_cualquiera_no(self):
        a = AlcanceEscritura()
        a.registrar(error=RuntimeError("boom"))
        assert not a.nunca_llego

    def test_fuera_de_un_rastreo_es_no_op(self):
        registrar_intento_escritura(SIN_CONEXION)

    def test_el_alcance_sobrevive_a_la_salida_con_excepcion(self):
        with pytest.raises(ValueError):
            with rastrear_escrituras() as a:
                registrar_intento_escritura(SIN_CONEXION)
                raise ValueError("x")
        assert a.nunca_llego
        registrar_intento_escritura(OK)
        assert a.intentos == 1


class TestTransporteRegistra:
    def _driver(self, respuestas):
        drv = object.__new__(CiscoVendor)
        it = iter(respuestas)

        def _ejecutar(extravars, device, password):
            r = next(it)
            if isinstance(r, BaseException):
                raise r
            return r

        drv._ejecutar = _ejecutar
        return drv

    def test_aplicar_registra_cada_intento(self):
        drv = self._driver([RECHAZO_DEL_EQUIPO, SIN_CONEXION])
        dev = Device(name="d", host="192.0.2.50", vendor="cisco_ios",
                     username="a", encrypted_password="x", platform="ios")
        with rastrear_escrituras() as a:
            drv._aplicar({"lines": ["x"]}, dev, "p", op_label="t")
            drv._aplicar({"lines": ["x"]}, dev, "p", op_label="t")
        assert a.intentos == 2 and a.sin_conexion == 1
        assert not a.nunca_llego

    def test_aplicar_registra_la_excepcion_y_la_relanza(self):
        drv = self._driver([ConnectionRefusedError("Connection refused")])
        dev = Device(name="d", host="192.0.2.50", vendor="cisco_ios",
                     username="a", encrypted_password="x", platform="ios")
        with rastrear_escrituras() as a:
            with pytest.raises(ConnectionRefusedError):
                drv._aplicar({"lines": ["x"]}, dev, "p", op_label="t")
        assert a.nunca_llego


class _Coord:
    @contextlib.contextmanager
    def bloquear(self, device_id, timeout=None):
        yield

    def limitar(self, device_id):
        pass


class _Repo:
    def add(self, job):
        pass

    def iniciar_si_pendiente(self, job):
        if job.status != "pending":
            return False
        job.marcar_iniciado()
        return True


class _Eventos:
    def __init__(self):
        self.despachados = []

    def despachar(self, eventos):
        self.despachados.extend(eventos)


class _Devices:
    def __init__(self, device):
        self._d = device

    def get(self, name):
        return self._d


def _orq(device):
    return Orquestador(_Devices(device), {}, _Repo(), _Eventos(), _Coord())


def _device():
    d = Device(name="swcs01", host="192.0.2.50", vendor="cisco_ios",
               username="a", encrypted_password="x", platform="ios")
    d._driver = object()
    d._password = "p"
    return d


class _Recurso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.device = ""
        self.rollbacks = 0
        self.lecturas = 0

    def validar(self):
        pass

    def repositorio(self):
        return "fake"

    def reconciliar(self, device):
        self.lecturas += 1
        return {"existed": True, "actual": None}

    def aplicar(self, device, pre_state=None):
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        registrar_intento_escritura(r)
        return r

    def ejecutar_rollback(self, pre_state, device):
        self.rollbacks += 1
        return True, True


class _RecursoLote(_Recurso):
    NECESITA_ESTADO_FRESCO_ROLLBACK = False

    @classmethod
    def reconciliar_lote(cls, recursos, device):
        return [{"existed": True, "actual": None} for _ in recursos]

    def resolver_paso(self, device, actual):
        return ("op", None, {})


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda s: None)


class TestOrquestadorEjecutar:
    def _correr(self, respuestas, max_retries=1):
        rec = _Recurso(respuestas)
        job = Job(operation="fake", device="swcs01", max_retries=max_retries)
        with pytest.raises(Exception):
            _orq(_device()).ejecutar(rec, "swcs01", "tester", job)
        return rec, job

    @pytest.mark.parametrize("resultado", [SIN_CONEXION, RECHAZADA, NEGOCIACION])
    def test_sin_conexion_no_hay_rollback(self, resultado):
        rec, job = self._correr([resultado])
        assert rec.rollbacks == 0
        assert job.rollback_performed is False
        assert job.rollback_success is None

    @pytest.mark.parametrize("resultado", [TIMEOUT, CANAL_CERRADO, RECHAZO_DEL_EQUIPO, CON_SALIDA_PARCIAL])
    def test_si_pudo_llegar_hace_rollback_como_siempre(self, resultado):
        rec, job = self._correr([resultado])
        assert rec.rollbacks == 1

    def test_timeout_y_despues_sin_conexion_hace_rollback(self):
        rec, job = self._correr([TIMEOUT, SIN_CONEXION])
        assert rec.rollbacks == 1


class TestOrquestadorLote:
    def _correr(self, respuestas):
        rec = _RecursoLote(respuestas)
        job = Job(operation="fake", device="swcs01", max_retries=1)
        driver_calls = []

        class Driver:
            def aplicar_lote(self, pasos, device, password, op_label=""):
                r = rec.respuestas.pop(0) if len(rec.respuestas) > 1 else rec.respuestas[0]
                registrar_intento_escritura(r)
                driver_calls.append(op_label)
                return r

        dev = _device()
        dev._driver = Driver()
        orq = _orq(dev)
        rollbacks = []
        orq._rollback_lote = lambda *a, **k: (rollbacks.append(1) or [(True, True)], None)
        with pytest.raises(Exception):
            orq.ejecutar_lote([rec], "swcs01", "tester", job)
        return job, rollbacks

    def test_sin_conexion_no_hay_rollback_ni_sesiones_extra(self):
        job, rollbacks = self._correr([SIN_CONEXION])
        assert rollbacks == []
        assert job.rollback_performed is False
        assert job.rollback_success is None

    def test_si_pudo_llegar_hace_rollback(self):
        job, rollbacks = self._correr([TIMEOUT])
        assert rollbacks == [1] * len(rollbacks) and rollbacks
        assert job.rollback_performed is True


class TestFuenteUnicaDePatrones:
    @pytest.mark.parametrize("patron", PATRONES_SIN_CONEXION)
    def test_cada_patron_es_conectividad_transitoria_y_sin_conexion(self, patron):
        orq = _orq(_device())
        decision = orq._clasificar_error({"rc": 1, "stdout": "", "stderr": f"x {patron} y"})
        assert decision.classification == "transient"
        assert decision.categoria == "connectivity"
        assert _no_conecto({"rc": 1, "stdout": "", "stderr": f"x {patron} y"}, None)

    @pytest.mark.parametrize("patron", PATRONES_SIN_CONEXION)
    def test_cada_patron_tiene_el_mensaje_de_equipo_inalcanzable(self, patron):
        amigable = _orq(_device())._error_amigable(f"x {patron} y")
        assert amigable["error_summary"] == "Device unreachable on the network."

    def test_la_negociacion_no_cambia_el_reintento_pero_si_cuenta_como_sin_conexion(self):
        orq = _orq(_device())
        assert orq._clasificar_error(NEGOCIACION).categoria != "connectivity"
        assert _no_conecto(NEGOCIACION, None)
