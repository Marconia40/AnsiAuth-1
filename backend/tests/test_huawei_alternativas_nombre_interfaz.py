from __future__ import annotations

import itertools

import pytest

from app.models.device import Device
from app.services.vendors.huawei.driver import HuaweiVendor


class _Equipo:
    def __init__(self, acepta_corto: bool, acepta_commit: bool):
        self.acepta_corto = acepta_corto
        self.acepta_commit = acepta_commit
        self.interfaces_usadas: list[str] = []

    def correr(self, bloques: list[str]) -> dict:
        salida: list[str] = []
        vista, ok = "user", True
        for bloque in bloques:
            for linea in bloque.split("\n"):
                prompt = {"user": "<swhw01>", "sys": "[swhw01]", "if": "[swhw01-GigabitEthernet0/0/25]"}[vista]
                salida.append(prompt + linea)
                if linea == "system-view":
                    vista = "sys"
                elif linea == "quit":
                    vista = {"if": "sys", "sys": "user", "user": "user"}[vista]
                elif linea.startswith("interface "):
                    nombre = linea.split()[1]
                    self.interfaces_usadas.append(nombre)
                    if nombre.startswith("GigabitEthernet") or self.acepta_corto and nombre.startswith("GE"):
                        vista = "if"
                    else:
                        salida.append("        ^\nError: Wrong parameter found at '^' position.")
                        ok = False
                elif linea == "commit" and not self.acepta_commit:
                    salida.append("        ^\nError: Unrecognized command found at '^' position.")
                    ok = False
                elif vista != "if":
                    salida.append("        ^\nError: Unrecognized command found at '^' position.")
                    ok = False
        texto = "\n".join(salida)
        return {"rc": 0 if ok else 2, "stdout": texto, "stderr": "", "stdouts": [texto]}


def _driver(equipo: _Equipo):
    drv = object.__new__(HuaweiVendor)
    intentos: list[list[str]] = []

    def _aplicar(extravars, device, password, *, op_label):
        bloques = extravars.get("command_blocks") or [extravars["command_block"]]
        intentos.append(bloques)
        r = equipo.correr(bloques)
        return {**r, "success": r["rc"] == 0}

    drv._aplicar = _aplicar
    return drv, intentos


def _device() -> Device:
    return Device(name="swhw01", host="192.0.2.50", vendor="huawei_vrp",
                  username="a", encrypted_password="x", platform="vrp")


def _pasos(drv):
    i = "GE0/0/25"
    return {
        "desc": drv.resolver_update_port_description(i, "x"),
        "admin_on": drv.resolver_set_port_admin_state(i, True),
        "admin_off": drv.resolver_set_port_admin_state(i, False),
        "vlan": drv.resolver_set_port_access_vlan(i, 10),
        "access_conf": drv.resolver_set_access_mode(i, 10),
        "access_sin": drv.resolver_set_access_mode(i, 10, viene_de_trunk_con_vlans=False),
        "storm_on": drv.resolver_set_storm_control(i, True, 10, "shutdown", True),
        "storm_off": drv.resolver_set_storm_control(i, False, None),
        "poe_on": drv.resolver_set_port_poe(i, True),
    }


class TestLoteEnEquipoQueExigeNombreCompletoYNoTieneCommit:
    def test_el_caso_real_access_mas_undo_shutdown(self):
        equipo = _Equipo(acepta_corto=False, acepta_commit=False)
        drv, intentos = _driver(equipo)
        p = _pasos(drv)

        resultado = drv.aplicar_lote([p["access_conf"], p["admin_on"]], _device(), "p", op_label="lote_puerto")

        assert resultado["success"], resultado["stdout"]
        assert all("interface GE0/0/25" not in b for b in intentos[-1])

    def test_ninguna_combinacion_de_hasta_3_pasos_termina_con_el_nombre_corto(self):
        fallas = []
        for r in (2, 3):
            for combo in itertools.permutations(_pasos(object.__new__(HuaweiVendor)), r):
                equipo = _Equipo(acepta_corto=False, acepta_commit=False)
                drv, _ = _driver(equipo)
                p = _pasos(drv)
                res = drv.aplicar_lote([p[k] for k in combo], _device(), "p", op_label="lote_puerto")
                if not res["success"]:
                    fallas.append(combo)
        assert fallas == []

    def test_un_solo_paso_por_el_camino_individual(self):
        equipo = _Equipo(acepta_corto=False, acepta_commit=False)
        drv, _ = _driver(equipo)
        op, variante, vars = _pasos(drv)["access_conf"]

        resultado = drv._aplicar_desde_template(op, vars, _device(), "p", variant=variante)

        assert resultado["success"], resultado["stdout"]


class TestEquipoQueExigeNombreCorto:
    def test_no_se_pasa_al_nombre_completo_si_nunca_hizo_falta(self):
        equipo = _Equipo(acepta_corto=True, acepta_commit=False)
        drv, intentos = _driver(equipo)
        p = _pasos(drv)

        resultado = drv.aplicar_lote([p["access_conf"], p["admin_on"]], _device(), "p", op_label="lote_puerto")

        assert resultado["success"], resultado["stdout"]
        assert all(nombre == "GE0/0/25" for nombre in equipo.interfaces_usadas)


class TestVarsTrasAlternativa:
    VARS = {"interface": "GE0/0/25", "interface_full": "GigabitEthernet0/0/25"}

    def test_una_alternativa_con_nombre_completo_fija_el_nombre_completo(self):
        alt = {"block": ["system-view", "interface {interface_full}", "undo shutdown"]}
        assert HuaweiVendor._vars_tras_alternativa(self.VARS, alt)["interface"] == "GigabitEthernet0/0/25"

    def test_una_alternativa_con_nombre_corto_no_cambia_nada(self):
        alt = {"block": ["system-view", "interface {interface}", "undo shutdown"]}
        assert HuaweiVendor._vars_tras_alternativa(self.VARS, alt) is self.VARS

    def test_sin_interface_full_no_hace_nada(self):
        vars = {"vlan_id": 10}
        assert HuaweiVendor._vars_tras_alternativa(vars, {"lines": ["x {vlan_id}"]}) is vars
