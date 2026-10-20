from __future__ import annotations

import contextlib

from app.models.device import Device
from app.models.global_config import GlobalConfig
from app.models.job import Job
from app.models.port import Puerto
from app.models.svi import SVI
from app.services import ssh_direct_service
from app.services.orquestador import Orquestador


def _device(vendor: str = "huawei_vrp") -> Device:
    d = Device(
        name="swhw01", host="192.0.2.50", vendor=vendor,
        username="admin", encrypted_password="x", platform="vrp",
    )
    d._driver = object()
    d._password = "fake-password"
    return d


class _FakeCoordinador:
    @contextlib.contextmanager
    def bloquear(self, device_id: str, timeout=None):
        yield

    def limitar(self, device_id: str) -> None:
        pass


class _FakeRepo:
    def __init__(self):
        self.added: list = []

    def add(self, job) -> None:
        self.added.append(job)

    def iniciar_si_pendiente(self, job) -> bool:
        if job.status != "pending":
            return False
        job.marcar_iniciado()
        self.added.append(job)
        return True

    def get(self, name):
        return None


class _FakeEventos:
    def __init__(self):
        self.despachados: list = []

    def despachar(self, eventos) -> None:
        self.despachados.extend(eventos)


def _orquestador(device: Device) -> Orquestador:
    orq = object.__new__(Orquestador)
    orq._device_repo = _FakeDeviceRepo(device)
    orq._jobs = _FakeRepo()
    orq._eventos = _FakeEventos()
    orq._coordinador = _FakeCoordinador()
    return orq


class _FakeDeviceRepo:
    def __init__(self, device: Device):
        self._device = device

    def get(self, name: str):
        return self._device if name == self._device.name else None


class TestNoOpRollback:
    def test_svi_acl_resolver_rollback_no_op_cuando_nada_se_aplico(self):
        class FakeDriver:
            def resolver_set_svi_acl(self, *a, **k):
                raise AssertionError("no debería llamarse -- nada que revertir")

        device = _device()
        device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", acl_in="dasfdf")
        pre_state = {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", acl_in=None)}
        actual_ahora = SVI(vlan_id=50, device="swhw01", acl_in=None)

        pasos, verificar = snap.resolver_rollback(pre_state, device, actual_ahora)

        assert pasos == []
        assert verificar is None

    def test_svi_acl_resolver_restore_no_op_cuando_nada_se_aplico(self):
        class FakeDriver:
            def resolver_set_svi_acl(self, *a, **k):
                raise AssertionError("no debería llamarse -- nada que revertir")

        device = _device()
        device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", acl_in="")
        actual_ahora = SVI(vlan_id=50, device="swhw01", acl_in=None)

        pasos, verificar = snap.resolver_restore(device, actual_ahora)

        assert pasos == []

    def test_puerto_resolver_rollback_no_op_cuando_nada_cambio(self):
        class FakeDriver:
            def resolver_set_access_mode(self, *a, **k):
                raise AssertionError("no debería llamarse")

        device = _device()
        device._driver = FakeDriver()
        snap = Puerto(interface="GE0/0/10", device="swhw01", mode="access", access_vlan=10)
        pre_state = {"existed": False, "actual": None}

        pasos, verificar = snap.resolver_rollback(pre_state, device)

        assert pasos == []
        assert verificar is None


class TestRevertRealAplicado:
    def test_svi_acl_resolver_rollback_revierte_cuando_si_se_aplico(self):
        llamadas = []

        class FakeDriver:
            def resolver_set_svi_acl(self, vlan_id, direction, acl_name, current_acl_name=None):
                llamadas.append((vlan_id, direction, acl_name, current_acl_name))
                return ("set_svi_acl", "clear_named", {"vlan_id": vlan_id, "acl_name": acl_name})

        device = _device()
        device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", acl_in="dasfdf")
        pre_state = {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", acl_in="old-acl")}
        actual_ahora = SVI(vlan_id=50, device="swhw01", acl_in="dasfdf")

        pasos, verificar = snap.resolver_rollback(pre_state, device, actual_ahora)

        assert len(pasos) == 1
        assert llamadas == [(50, "in", "old-acl", "dasfdf")]
        assert verificar(SVI(vlan_id=50, device="swhw01", acl_in="old-acl")) is True
        assert verificar(SVI(vlan_id=50, device="swhw01", acl_in="dasfdf")) is False

    def test_puerto_ejecutar_rollback_revierte_trunk_con_vlans(self):
        class FakeDriver:
            def set_trunk_mode(self, iface, pvid, vlans, device, password):
                return {"rc": 0}
            def list_ports(self, device, password):
                return [Puerto(interface="GE0/0/10", device="swhw01", mode="trunk", access_vlan=10, allowed_vlans=[10, 20])]

        device = _device()
        device._driver = FakeDriver()
        puerto = Puerto(interface="GE0/0/10", device="swhw01", mode="access", access_vlan=1060)
        anterior = Puerto(interface="GE0/0/10", device="swhw01", mode="trunk", access_vlan=10, allowed_vlans=[10, 20])
        pre_state = {"existed": True, "actual": anterior}

        performed, success = puerto.ejecutar_rollback(pre_state, device)

        assert (performed, success) == (True, True)

    def test_puerto_resolver_rollback_storm_control_previamente_deshabilitado_revierte(self):
        llamadas = []

        class FakeDriver:
            def resolver_set_storm_control(self, interface, enabled, threshold, action="shutdown", trap=True):
                llamadas.append((interface, enabled, threshold))
                return ("set_storm_control", "disabled", {"interface": interface})

        device = _device()
        device._driver = FakeDriver()
        snap = Puerto(
            interface="Gi1/0/1", device="swcs01",
            storm_control_enabled=True, storm_control_threshold=10,
        )
        anterior = Puerto(
            interface="Gi1/0/1", device="swcs01",
            storm_control_enabled=False, storm_control_threshold=None,
        )
        pre_state = {"existed": True, "actual": anterior}

        pasos, verificar = snap.resolver_rollback(pre_state, device)

        assert len(pasos) == 1
        assert llamadas == [("Gi1/0/1", False, None)]


class TestRollbackStormControl:
    @staticmethod
    def _device_con(llamadas):
        class FakeDriver:
            def resolver_set_storm_control(self, interface, enabled, threshold, action="shutdown", trap=True):
                llamadas.append(("plan", interface, enabled, threshold, action, trap))
                return ("set_storm_control", "enabled" if enabled else "disabled", {"interface": interface})

            def set_storm_control(self, interface, enabled, threshold, action, trap, device, password):
                llamadas.append(("exec", interface, enabled, threshold, action, trap))
                return {"rc": 0, "stdout": "", "stderr": ""}

            def list_ports(self, device, password):
                return []

        device = _device()
        device._driver = FakeDriver()
        return device

    @staticmethod
    def _snap_y_pre(**anterior):
        snap = Puerto(
            interface="Gi1/0/1", device="swcs01",
            storm_control_enabled=True, storm_control_threshold=20,
        )
        return snap, {"existed": True, "actual": Puerto(interface="Gi1/0/1", device="swcs01", **anterior)}

    def test_lote_restaura_action_y_trap_previos(self):
        llamadas: list = []
        device = self._device_con(llamadas)
        snap, pre = self._snap_y_pre(
            storm_control_enabled=True, storm_control_threshold=10,
            storm_control_action="filter", storm_control_trap=False,
        )

        pasos, _ = snap.resolver_rollback(pre, device)

        assert len(pasos) == 1
        assert llamadas == [("plan", "Gi1/0/1", True, 10, "filter", False)]

    def test_lote_action_y_trap_sin_leer_usan_los_defaults_del_apply(self):
        llamadas: list = []
        device = self._device_con(llamadas)
        snap, pre = self._snap_y_pre(storm_control_enabled=True, storm_control_threshold=10)

        snap.resolver_rollback(pre, device)

        assert llamadas == [("plan", "Gi1/0/1", True, 10, "shutdown", True)]

    def test_lote_threshold_ilegible_con_storm_control_activo_no_restaura(self):
        llamadas: list = []
        device = self._device_con(llamadas)
        snap, pre = self._snap_y_pre(storm_control_enabled=True, storm_control_threshold=None)

        pasos, verificar = snap.resolver_rollback(pre, device)

        assert pasos == []
        assert llamadas == []

    def test_lote_estado_previo_desconocido_no_toca(self):
        llamadas: list = []
        device = self._device_con(llamadas)
        snap, pre = self._snap_y_pre(storm_control_enabled=None)

        pasos, _ = snap.resolver_rollback(pre, device)

        assert pasos == [] and llamadas == []

    def test_reset_en_lote_restaura_storm_control_completo(self):
        llamadas: list = []
        device = self._device_con(llamadas)
        snap = Puerto(interface="Gi1/0/1", device="swcs01", reset=True)
        pre = {"existed": True, "actual": Puerto(
            interface="Gi1/0/1", device="swcs01",
            storm_control_enabled=True, storm_control_threshold=15,
            storm_control_action="filter", storm_control_trap=True,
        )}

        snap.resolver_rollback(pre, device)

        assert ("plan", "Gi1/0/1", True, 15, "filter", True) in llamadas

    def test_reset_single_llama_a_set_storm_control_con_la_aridad_correcta(self):
        llamadas: list = []
        device = self._device_con(llamadas)
        snap = Puerto(interface="Gi1/0/1", device="swcs01", reset=True)
        pre = {"existed": True, "actual": Puerto(
            interface="Gi1/0/1", device="swcs01",
            storm_control_enabled=True, storm_control_threshold=15,
            storm_control_action="filter", storm_control_trap=False,
        )}

        snap.ejecutar_rollback(pre, device)

        assert ("exec", "Gi1/0/1", True, 15, "filter", False) in llamadas


class TestRollbackLoteDosFases:
    def test_apply_falla_marca_todos_los_recursos_con_pasos_uniforme(self):
        class FakeDriver:
            def aplicar_lote(self, pasos, device, password, op_label=""):
                return {"rc": 1, "stdout": "", "stderr": "device rejected"}
            def resolver_set_svi_description(self, vlan_id, desc):
                return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})
            def get_svis(self, device, password):
                return []

        device = _device()
        device._driver = FakeDriver()
        orq = _orquestador(device)

        recursos = [
            SVI(vlan_id=50, device="swhw01", description="a"),
            SVI(vlan_id=51, device="swhw01", description="b"),
        ]
        pre_states = [
            {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", description="old-a")},
            {"existed": True, "actual": SVI(vlan_id=51, device="swhw01", description="old-b")},
        ]

        resultados, error_rb = orq._rollback_lote(recursos, pre_states, device)

        assert resultados == [(True, False), (True, False)]
        assert error_rb is not None

    def test_apply_ok_pero_1_de_2_no_verifica(self):
        class FakeDriver:
            def aplicar_lote(self, pasos, device, password, op_label=""):
                return {"rc": 0, "stdout": "ok", "stderr": ""}
            def resolver_set_svi_description(self, vlan_id, desc):
                return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})

        class ReadDriver(FakeDriver):
            def __init__(self):
                self.estado = {50: "a", 51: "b"}

            def aplicar_lote(self, pasos, device, password, op_label=""):
                for _op, _variante, vars in pasos:
                    self.estado[vars["vlan_id"]] = "MISMATCH" if vars["vlan_id"] == 51 else vars["description"]
                return {"rc": 0, "stdout": "ok", "stderr": ""}

            def get_svis(self, device, password):
                return [SVI(vlan_id=v, device="swhw01", description=d) for v, d in self.estado.items()]

        device = _device()
        device._driver = ReadDriver()
        orq = _orquestador(device)

        recursos = [
            SVI(vlan_id=50, device="swhw01", description="a"),
            SVI(vlan_id=51, device="swhw01", description="b"),
        ]
        pre_states = [
            {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", description="old-a")},
            {"existed": True, "actual": SVI(vlan_id=51, device="swhw01", description="old-b")},
        ]

        resultados, error_rb = orq._rollback_lote(recursos, pre_states, device)

        assert resultados == [(True, True), (True, False)]
        assert error_rb is not None


class _SviQueNoSePuedePlanear(SVI):
    def resolver_rollback(self, pre_state, device, actual_ahora=None):
        raise RuntimeError("estado previo ilegible")


class TestRollbackLoteRecursoSinPlan:
    def _driver(self, enviados):
        class FakeDriver:
            estado = {50: "old-a", 51: "b"}

            def aplicar_lote(self, pasos, device, password, op_label=""):
                enviados.append(list(pasos))
                for _op, _variante, vars in pasos:
                    self.estado[vars["vlan_id"]] = vars["description"]
                return {"rc": 0, "stdout": "ok", "stderr": ""}
            def resolver_set_svi_description(self, vlan_id, desc):
                return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})
            def get_svis(self, device, password):
                return [SVI(vlan_id=v, device="swhw01", description=d) for v, d in self.estado.items()]
        return FakeDriver()

    def test_el_que_no_se_puede_planear_no_arrastra_a_los_demas(self):
        enviados: list = []
        device = _device()
        device._driver = self._driver(enviados)
        orq = _orquestador(device)

        recursos = [
            _SviQueNoSePuedePlanear(vlan_id=50, device="swhw01", description="a"),
            SVI(vlan_id=51, device="swhw01", description="b"),
        ]
        pre_states = [
            {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", description="old-a")},
            {"existed": True, "actual": SVI(vlan_id=51, device="swhw01", description="old-b")},
        ]

        resultados, error_rb = orq._rollback_lote(recursos, pre_states, device)

        assert len(enviados) == 1
        assert [p[0] for p in enviados[0]] == ["set_svi_description"]
        assert all(op != "__error__" for op, _v, _vars in enviados[0])
        assert resultados == [(True, False), (True, True)]
        assert error_rb is not None
        assert "could not be planned" in error_rb and "resource #1" in error_rb
        assert "estado previo ilegible" in error_rb

    def test_si_ninguno_se_puede_planear_no_se_abre_sesion_de_escritura(self):
        enviados: list = []
        device = _device()
        device._driver = self._driver(enviados)
        orq = _orquestador(device)

        recursos = [
            _SviQueNoSePuedePlanear(vlan_id=50, device="swhw01", description="a"),
            _SviQueNoSePuedePlanear(vlan_id=51, device="swhw01", description="b"),
        ]
        pre_states = [{"existed": True, "actual": SVI(vlan_id=v, device="swhw01")} for v in (50, 51)]

        resultados, error_rb = orq._rollback_lote(recursos, pre_states, device)

        assert enviados == []
        assert resultados == [(True, False), (True, False)]
        assert error_rb is not None and "resource #2" in error_rb

    def test_si_el_apply_del_rollback_falla_se_conserva_su_error_y_el_del_plan(self):
        device = _device()

        class FakeDriver:
            def aplicar_lote(self, pasos, device, password, op_label=""):
                return {"rc": 1, "stdout": "", "stderr": "device rejected"}
            def resolver_set_svi_description(self, vlan_id, desc):
                return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})
            def get_svis(self, device, password):
                return []

        device._driver = FakeDriver()
        orq = _orquestador(device)
        recursos = [
            _SviQueNoSePuedePlanear(vlan_id=50, device="swhw01", description="a"),
            SVI(vlan_id=51, device="swhw01", description="b"),
        ]
        pre_states = [
            {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", description="old-a")},
            {"existed": True, "actual": SVI(vlan_id=51, device="swhw01", description="old-b")},
        ]

        resultados, error_rb = orq._rollback_lote(recursos, pre_states, device)

        assert resultados == [(True, False), (True, False)]
        assert "device rejected" in error_rb and "could not be planned" in error_rb


class TestRetryRollbackDosFases:
    def test_retry_rollback_falla_cuando_verificacion_no_coincide(self):
        class FakeDriver:
            def aplicar_lote(self, pasos, device, password, op_label=""):
                return {"rc": 0, "stdout": "ok", "stderr": ""}
            def get_svis(self, device, password):
                return [SVI(vlan_id=50, device="swhw01", description="WRONG")]
            def resolver_set_svi_description(self, vlan_id, desc):
                return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})

        device = _device()
        device._driver = FakeDriver()
        orq = _orquestador(device)

        original_job = Job(
            operation="svi", device="swhw01", max_retries=1,
            pre_state={"lote": [{
                "existed": True,
                "actual": SVI(vlan_id=50, device="swhw01", description="restored").to_dict(),
            }]},
        )
        new_job = Job(operation="retry_rollback", device="swhw01", max_retries=1)

        raised = False
        try:
            orq.retry_rollback(original_job, new_job, actor="tester")
        except Exception:
            raised = True

        assert raised is True
        assert new_job.status == "failed"

    def test_retry_rollback_completa_cuando_todo_verifica(self):
        class FakeDriver:
            def aplicar_lote(self, pasos, device, password, op_label=""):
                return {"rc": 0, "stdout": "ok", "stderr": ""}
            def get_svis(self, device, password):
                return [SVI(vlan_id=50, device="swhw01", description="restored")]
            def resolver_set_svi_description(self, vlan_id, desc):
                return ("set_svi_description", None, {"vlan_id": vlan_id, "description": desc})

        device = _device()
        device._driver = FakeDriver()
        orq = _orquestador(device)

        original_job = Job(
            operation="svi", device="swhw01", max_retries=1,
            pre_state={"lote": [{
                "existed": True,
                "actual": SVI(vlan_id=50, device="swhw01", description="restored").to_dict(),
            }]},
        )
        new_job = Job(operation="retry_rollback", device="swhw01", max_retries=1)

        orq.retry_rollback(original_job, new_job, actor="tester")

        assert new_job.status == "completed"


class TestRetryRollbackSinPasosRepetidos:
    def _driver(self, enviados):
        class FakeDriver:
            estado = ["10.0.0.99"]

            def aplicar_lote(self, pasos, device, password, op_label=""):
                enviados.append(list(pasos))
                seen = set()
                for _op, _v, vars in pasos:
                    for ip in vars["remove"]:
                        if ip not in self.estado:
                            return {"rc": 1, "stdout": "", "stderr": "Error: The DHCP server IP address does not exist."}
                        self.estado.remove(ip)
                    for ip in vars["add"]:
                        if ip not in self.estado:
                            self.estado.append(ip)
                return {"rc": 0, "stdout": "ok", "stderr": ""}

            def get_svis(self, device, password):
                return [SVI(vlan_id=50, device="swhw01", dhcp_relay_servers=list(self.estado), ipv4_address="10.0.0.1/24")]

            def resolver_set_svi_dhcp_relay_delta(self, vlan_id, add, remove, final, layout=None, indices_previos=None):
                return ("delta", None, {"vlan_id": vlan_id, "add": list(add), "remove": list(remove)})

            def resolver_set_svi_dhcp_relay(self, vlan_id, servers):
                return ("full", None, {"vlan_id": vlan_id, "servers": list(servers)})
        return FakeDriver()

    def test_el_restore_de_la_misma_foto_se_manda_una_sola_vez(self):
        enviados: list = []
        device = _device()
        device._driver = self._driver(enviados)
        orq = _orquestador(device)
        foto = SVI(vlan_id=50, device="swhw01", dhcp_relay_servers=["10.0.0.27"], ipv4_address="10.0.0.1/24").to_dict()
        original_job = Job(
            operation="svi", device="swhw01", max_retries=1,
            pre_state={"lote": [{"existed": True, "actual": foto}, {"existed": True, "actual": foto}]},
        )
        new_job = Job(operation="retry_rollback", device="swhw01", max_retries=1)

        orq.retry_rollback(original_job, new_job, actor="tester")

        assert len(enviados) == 1 and len(enviados[0]) == 1
        assert enviados[0][0][2] == {"vlan_id": 50, "add": ["10.0.0.27"], "remove": ["10.0.0.99"]}
        assert new_job.status == "completed"

    def test_pasos_distintos_se_conservan_en_orden(self):
        from app.services.orquestador import _sin_pasos_repetidos
        a, b = ("op", None, {"x": 1}), ("op", None, {"x": 2})
        assert _sin_pasos_repetidos([a, b, a, b, a]) == [a, b]
        assert _sin_pasos_repetidos([]) == []


class TestRuidoBenigno:
    def test_placeholder_y_rechazado_no_cuenta_como_error(self):
        raw = (
            "[swhw01-GigabitEthernet0/0/40]y\n"
            "                               ^\n"
            "Error: Unrecognized command found at '^' position."
        )
        assert ssh_direct_service._tiene_error(raw, vendor="huawei_vrp") is False

    def test_rechazo_real_de_sintaxis_si_cuenta_como_error(self):
        raw = "[swhw01]vlanx 99\n         ^\nError: Unrecognized command found at '^' position."
        assert ssh_direct_service._tiene_error(raw, vendor="huawei_vrp") is True

    def test_error_real_mezclado_con_ruido_benigno_si_cuenta(self):
        raw = (
            "[swhw01-GigabitEthernet0/0/40]y\n"
            "                               ^\n"
            "Error: Unrecognized command found at '^' position.\n"
            "% Invalid input detected"
        )
        assert ssh_direct_service._tiene_error(raw, vendor="huawei_vrp") is True


class TestErrorPatternsPorVendor:
    def test_cisco_invalid_input_detectado(self):
        raw = "% Invalid input detected at '^' marker."
        assert ssh_direct_service._tiene_error(raw, vendor="cisco_ios") is True

    def test_cisco_incomplete_command_detectado(self):
        raw = "switch(config)#interface\n% Incomplete command."
        assert ssh_direct_service._tiene_error(raw, vendor="cisco_ios") is True

    def test_cisco_ambiguous_command_detectado(self):
        raw = "% Ambiguous command:  \"sh ver\""
        assert ssh_direct_service._tiene_error(raw, vendor="cisco_ios") is True

    def test_huawei_unknown_command_sin_anchor_detectado(self):
        raw = "[swhw01]displaay clock\nUnknown command"
        assert ssh_direct_service._tiene_error(raw, vendor="huawei_vrp") is True

    def test_huawei_syntax_error_sin_anchor_detectado(self):
        raw = "[swhw01]vla 10\nSyntax error"
        assert ssh_direct_service._tiene_error(raw, vendor="huawei_vrp") is True

    def test_vendor_none_usa_regex_generico_de_siempre(self):
        raw = "algo unknown command sin anchor de linea"
        assert ssh_direct_service._tiene_error(raw) is False
        assert ssh_direct_service._tiene_error(raw, vendor="algun_vendor_no_existente") is False
        assert ssh_direct_service._tiene_error("% Invalid input detected") is True

    def test_aviso_cisco_autocreate_no_gana_señal_transitoria_real(self):
        from app.services.orquestador import Orquestador

        inst = object.__new__(Orquestador)
        raw = (
            "Connection to 10.237.61.126 closed by remote host.\n"
            "% Access VLAN does not exist. Creating vlan 1050"
        )
        decision = Orquestador._clasificar_error(inst, {"rc": 1, "stdout": raw, "stderr": ""})
        assert decision.classification == "transient"
        assert decision.reason == "closed by remote host"

    def test_error_amigable_no_engancha_ruido_no_relacionado(self):
        from app.services.orquestador import Orquestador

        inst = object.__new__(Orquestador)
        raw = (
            "Connection to 10.237.61.126 closed by remote host.\n"
            "swcs01(config-if)#ip address 192.168.100.50 255.255.255.0 secondary\n"
            "% 192.168.100.0 is assigned to Vlan10"
        )
        friendly = inst._error_amigable(raw)
        assert friendly["error_type"] == "permanent"
        assert friendly["error_reason"] == "is assigned to"
        assert friendly["error_summary"] == "The requested change conflicts with the device's current configuration."

    def test_invalid_address_es_permanente_no_transitorio(self):
        from app.services.orquestador import Orquestador

        inst = object.__new__(Orquestador)
        raw = (
            "Connection to 10.237.61.126 closed by remote host.\n"
            "swcs01(config)#ntp server 255.255.255.255\n"
            "% Invalid address"
        )
        decision = Orquestador._clasificar_error(inst, {"rc": 1, "stdout": raw, "stderr": ""})
        assert decision.classification == "permanent"
        assert decision.should_retry is False
        assert decision.reason == "invalid address"

    def test_is_invalid_es_permanente_no_unknown(self):
        from app.services.orquestador import Orquestador

        inst = object.__new__(Orquestador)
        raw = "Error: The specified IP address is invalid."
        decision = Orquestador._clasificar_error(inst, {"rc": 1, "stdout": raw, "stderr": ""})
        assert decision.classification == "permanent"
        assert decision.should_retry is False
        assert decision.reason == "is invalid"

    def test_can_not_support_es_permanente_no_unknown(self):
        from app.services.orquestador import Orquestador

        inst = object.__new__(Orquestador)
        raw = "Error: Interface GigabitEthernet0/0/19 can not support PoE."
        decision = Orquestador._clasificar_error(inst, {"rc": 1, "stdout": raw, "stderr": ""})
        assert decision.classification == "permanent"
        assert decision.should_retry is False
        assert decision.reason == "can not support"


class TestGlobalConfigNoOpRollback:
    def test_route_add_no_op_cuando_nunca_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", routes=[])
            def remove_route(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", route_add={"destination": "10.10.10.0/24", "next_hop": "10.10.10.1"})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", routes=[])}

        assert gc.ejecutar_rollback(pre_state, device) == (False, None)

    def test_route_add_revierte_cuando_si_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", routes=[{"destination": "10.10.10.0/24", "next_hop": "10.10.10.1"}])
            def remove_route(self, destino, next_hop, device, password):
                return {"rc": 0}

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", route_add={"destination": "10.10.10.0/24", "next_hop": "10.10.10.1"})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", routes=[])}

        performed, _success = gc.ejecutar_rollback(pre_state, device)
        assert performed is True

    def test_ntp_server_add_no_op_cuando_nunca_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", ntp_servers=[])
            def remove_ntp_server(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", ntp_server_add={"server": "10.0.0.1"})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", ntp_servers=[])}

        assert gc.ejecutar_rollback(pre_state, device) == (False, None)

    def test_dns_server_add_no_op_cuando_nunca_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", dns_servers=[])
            def remove_dns_server(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", dns_server_add={"server": "8.8.8.8"})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", dns_servers=[])}

        assert gc.ejecutar_rollback(pre_state, device) == (False, None)

    def test_log_server_add_no_op_cuando_nunca_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", log_servers=[])
            def remove_log_server(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", log_server_add={"server": "10.0.0.9"})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", log_servers=[])}

        assert gc.ejecutar_rollback(pre_state, device) == (False, None)

    def test_acl_create_nueva_no_op_cuando_nunca_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", acls=[])
            def delete_acl(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", acl_create={"name": "test-acl", "rules": [{"action": "permit"}]})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", acls=[])}

        assert gc.ejecutar_rollback(pre_state, device) == (False, None)

    def test_acl_create_nueva_revierte_cuando_si_se_aplico(self):
        class FakeDriver:
            def get_global_config(self, device, password):
                return GlobalConfig(device="swcs01", acls=[{"name": "test-acl", "rules": []}])
            def delete_acl(self, name, device, password):
                return {"rc": 0}

        device = _device(); device._driver = FakeDriver()
        gc = GlobalConfig(device="swcs01", acl_create={"name": "test-acl", "rules": [{"action": "permit"}]})
        pre_state = {"existed": True, "actual": GlobalConfig(device="swcs01", acls=[])}

        performed, _success = gc.ejecutar_rollback(pre_state, device)
        assert performed is True


class TestSVIIpv4SecondaryRollback:
    def test_ejecutar_rollback_no_op_cuando_ip_nunca_se_aplico(self):
        class FakeDriver:
            def get_svis(self, device, password):
                return [SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])]
            def set_svi_ipv4_secondary(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", ipv4_secondary_add="10.234.1.5/24")
        pre_state = {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])}

        assert snap.ejecutar_rollback(pre_state, device) == (False, None)

    def test_ejecutar_rollback_revierte_cuando_ip_si_se_aplico(self):
        class FakeDriver:
            def get_svis(self, device, password):
                return [SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=["10.234.1.5/24"])]
            def set_svi_ipv4_secondary(self, vlan_id, ip, prev, device, password):
                return {"rc": 0}

        device = _device(); device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", ipv4_secondary_add="10.234.1.5/24")
        pre_state = {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])}

        performed, _success = snap.ejecutar_rollback(pre_state, device)
        assert performed is True

    def test_resolver_rollback_no_op_cuando_ip_nunca_se_aplico(self):
        class FakeDriver:
            def resolver_set_svi_ipv4_secondary(self, *a, **k):
                raise AssertionError("no debería llamarse -- nunca se aplicó")

        device = _device(); device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", ipv4_secondary_add="10.234.1.5/24")
        pre_state = {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])}
        actual_ahora = SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])

        pasos, verificar = snap.resolver_rollback(pre_state, device, actual_ahora)
        assert pasos == []

    def test_resolver_rollback_revierte_y_verifica_correctamente(self):
        class FakeDriver:
            def resolver_set_svi_ipv4_secondary(self, vlan_id, ip, prev):
                return ("set_svi_ipv4_secondary", "clear", {"vlan_id": vlan_id})

        device = _device(); device._driver = FakeDriver()
        snap = SVI(vlan_id=50, device="swhw01", ipv4_secondary_add="10.234.1.5/24")
        pre_state = {"existed": True, "actual": SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])}
        actual_ahora = SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=["10.234.1.5/24"])

        pasos, verificar = snap.resolver_rollback(pre_state, device, actual_ahora)
        assert len(pasos) == 1
        assert verificar(SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=[])) is True
        assert verificar(SVI(vlan_id=50, device="swhw01", ipv4_address_secondary=["10.234.1.5/24"])) is False
