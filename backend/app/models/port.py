from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.models.rollback_por_estado import RollbackPorPlan, debe_revertir_escalar

PortMode = Literal["access", "trunk", "unknown"]
PortKind = Literal["physical", "aggregate"]

_INTERFACE_NAME_RE = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9_./:\-]{1,63}$")

_MAX_DESCRIPTION_LEN = 200

_DESCRIPTION_INVALID_RE = re.compile(r"[\x00-\x1f\x7f]")


def _validate_interface_name(interface: str) -> None:
    if not isinstance(interface, str) or not interface:
        raise ValueError("Interface name is required")
    if not _INTERFACE_NAME_RE.match(interface):
        raise ValueError(
            "Invalid interface name. Allowed characters are letters, digits, "
            "'.', '/', ':', '_', and '-'; name must start with a letter or "
            "digit and be 2–64 characters long."
        )


def _validate_access_vlan_id(vlan_id: int) -> None:
    if isinstance(vlan_id, bool) or not isinstance(vlan_id, int):
        raise ValueError("VLAN ID must be an integer")
    if vlan_id < 1 or vlan_id > 4094:
        raise ValueError(f"VLAN ID {vlan_id} is out of range (1-4094)")
    if vlan_id in (1002, 1003, 1004, 1005):
        raise ValueError(
            f"VLAN {vlan_id} is reserved (Cisco IOS legacy FDDI/Token-Ring) "
            "and cannot be assigned as an access VLAN"
        )


def _validate_trunk_vlan_id(vlan_id: int) -> None:
    if isinstance(vlan_id, bool) or not isinstance(vlan_id, int):
        raise ValueError("VLAN ID must be an integer")
    if vlan_id < 1 or vlan_id > 4094:
        raise ValueError(f"VLAN ID {vlan_id} is out of range (1-4094)")
    if vlan_id in (1002, 1003, 1004, 1005):
        raise ValueError(
            f"VLAN {vlan_id} is reserved (Cisco IOS legacy FDDI/Token-Ring) "
            "and cannot appear in a trunk allowed-VLAN list"
        )


def _validate_trunk_vlan_list(vlans: list) -> None:
    if not isinstance(vlans, list):
        raise ValueError("vlans must be a list of integers")
    if len(vlans) == 0:
        raise ValueError("vlans must not be empty")
    for v in vlans:
        _validate_trunk_vlan_id(v)


def _validate_description(description: "str | None") -> None:
    if description is None:
        return
    if not isinstance(description, str):
        raise ValueError("Description must be a string")
    if len(description) > _MAX_DESCRIPTION_LEN:
        raise ValueError(
            f"Description must not exceed {_MAX_DESCRIPTION_LEN} characters"
        )
    if _DESCRIPTION_INVALID_RE.search(description):
        raise ValueError("Description must not contain control characters or newlines")


def _viene_de_trunk_con_vlans(anterior: "Puerto | None") -> bool:
    if anterior is None:
        return True
    return anterior.mode == "trunk" and bool(anterior.allowed_vlans)


@dataclass
class Puerto(RollbackPorPlan):
    interface: str
    device: str = ""
    description: str | None = None
    admin_up: bool | None = None
    mode: PortMode | None = None
    access_vlan: int | None = None
    allowed_vlans: list[int] | None = None
    allowed_vlan_operation: str = "add"
    poe_enabled: bool | None = None
    storm_control_enabled: bool | None = None
    storm_control_threshold: float | None = None
    storm_control_action: str | None = None
    storm_control_trap: bool | None = None
    reset: bool = False
    operational_up: bool | None = None
    speed: str | None = None
    duplex: str | None = None
    kind: PortKind = "physical"

    NECESITA_ESTADO_FRESCO_ROLLBACK = True

    def __post_init__(self) -> None:
        _validate_interface_name(self.interface)

    @property
    def mutation_fields(self) -> set[str]:
        campos = ("description", "admin_up", "mode", "access_vlan",
                  "allowed_vlans", "poe_enabled", "storm_control_enabled",
                  "storm_control_threshold", "storm_control_action",
                  "storm_control_trap")
        return {c for c in campos if getattr(self, c) is not None}

    def validar(self) -> None:
        if self.reset:
            return
        if not self.mutation_fields:
            raise ValueError(
                "at least one mutation field must be provided "
                "(description, admin_up, mode, access_vlan, allowed_vlans, "
                "poe_enabled, storm_control_enabled, or reset)"
            )
        if self.storm_control_enabled is True and self.storm_control_threshold is None:
            raise ValueError("storm_control_enabled=True requires 'storm_control_threshold' to be set")
        if self.storm_control_threshold is not None and not (0 <= self.storm_control_threshold <= 100):
            raise ValueError("storm_control_threshold must be between 0 and 100")
        if (self.storm_control_action is not None or self.storm_control_trap is not None) \
                and self.storm_control_enabled is not True:
            raise ValueError(
                "storm_control_action/storm_control_trap require 'storm_control_enabled=True' "
                "in the same call"
            )
        if self.storm_control_action is not None and self.storm_control_action not in ("filter", "shutdown"):
            raise ValueError("storm_control_action must be 'filter' or 'shutdown'")
        if self.mode == "access" and self.access_vlan is None:
            raise ValueError("mode='access' requires 'access_vlan' to be set")
        if self.mode == "trunk":
            if self.access_vlan is None:
                raise ValueError("mode='trunk' requires 'access_vlan' (native VLAN/PVID) to be set")
            if not self.allowed_vlans:
                raise ValueError("mode='trunk' requires 'allowed_vlans' to be set")
        if self.access_vlan is not None:
            _validate_access_vlan_id(self.access_vlan)
        if self.allowed_vlans is not None:
            _validate_trunk_vlan_list(self.allowed_vlans)
        if self.description is not None:
            _validate_description(self.description)

    def reconciliar(self, device: "Device") -> dict:
        puertos = device.driver.list_ports(device, device.password)
        existente = next((p for p in puertos if p.interface == self.interface), None)
        return {"existed": existente is not None, "actual": existente}

    @staticmethod
    def reconciliar_lote(recursos: "list[Puerto]", device: "Device") -> "list[dict]":
        puertos = device.driver.list_ports(device, device.password)
        por_interfaz = {p.interface: p for p in puertos}
        return [
            {"existed": r.interface in por_interfaz, "actual": por_interfaz.get(r.interface)}
            for r in recursos
        ]

    def aplicar(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        if self.reset:
            return self._aplicar_reset(device)
        if self.mode == "access":
            return self._aplicar_modo_access(device, pre_state)
        if self.mode == "trunk":
            return self._aplicar_modo_trunk(device, pre_state)
        campos = self.mutation_fields
        if "storm_control_enabled" in campos:
            return self._aplicar_storm_control(device, pre_state)
        if len(campos) != 1:
            raise ValueError(
                f"Puerto.aplicar(): sin mode seteado se espera exactamente "
                f"1 campo de mutación (se recibieron {sorted(campos)}) -- "
                f"las únicas combinaciones válidas de 2+ campos son "
                f"mode='access'+access_vlan, mode='trunk'+allowed_vlans, o "
                f"storm_control_enabled(+storm_control_threshold)"
            )
        campo = next(iter(campos))
        if campo == "description":
            return self._aplicar_description(device, pre_state)
        if campo == "admin_up":
            return self._aplicar_admin_up(device, pre_state)
        if campo == "access_vlan":
            return self._aplicar_access_vlan(device, pre_state)
        if campo == "allowed_vlans":
            return self._aplicar_allowed_vlans(device, pre_state)
        if campo == "poe_enabled":
            return self._aplicar_poe(device, pre_state)
        raise ValueError(f"Puerto.aplicar(): no hay driver call para el campo {campo!r}")

    def resolver_paso(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        if self.reset:
            return device.driver.resolver_reset_port(self.interface)
        if self.mode == "access":
            return device.driver.resolver_set_access_mode(
                self.interface, self.access_vlan,
                viene_de_trunk_con_vlans=_viene_de_trunk_con_vlans(actual),
            )
        if self.mode == "trunk":
            return self._resolver_modo_trunk(device, actual)
        campos = self.mutation_fields
        if "storm_control_enabled" in campos:
            return self._resolver_storm_control(device, actual)
        if len(campos) != 1:
            raise ValueError(
                f"Puerto.resolver_paso(): sin mode seteado se espera exactamente "
                f"1 campo de mutación (se recibieron {sorted(campos)}) -- "
                f"las únicas combinaciones válidas de 2+ campos son "
                f"mode='access'+access_vlan, mode='trunk'+allowed_vlans, o "
                f"storm_control_enabled(+storm_control_threshold)"
            )
        campo = next(iter(campos))
        if campo == "description":
            return self._resolver_description(device, actual)
        if campo == "admin_up":
            return self._resolver_admin_up(device, actual)
        if campo == "access_vlan":
            return self._resolver_access_vlan(device, actual)
        if campo == "allowed_vlans":
            return self._resolver_allowed_vlans(device, actual)
        if campo == "poe_enabled":
            return self._resolver_poe(device, actual)
        raise ValueError(f"Puerto.resolver_paso(): no hay driver call para el campo {campo!r}")

    def resolver_rollback(
        self, pre_state: dict, device: "Device", actual_ahora: "Puerto | None" = None,
    ) -> "tuple[list, Any]":
        if not pre_state.get("existed"):
            return [], None
        anterior = pre_state.get("actual")
        if anterior is None:
            return [], None

        if self.reset:
            return self._resolver_rollback_reset(anterior, device)

        campos = self.mutation_fields
        paso = None

        if self.mode in ("access", "trunk"):
            if self.mode == "trunk" and self._calcular_trunk_config(anterior) is not None:
                return self._resolver_rollback_modo_trunk(anterior, device, actual_ahora)
            if anterior.mode == "access":
                if anterior.access_vlan is None:
                    return [], None
                paso = device.driver.resolver_set_access_mode(self.interface, int(anterior.access_vlan))
            elif anterior.mode == "trunk":
                if anterior.access_vlan is None or not anterior.allowed_vlans:
                    return [], None
                paso = device.driver.resolver_set_trunk_mode(
                    self.interface, int(anterior.access_vlan), list(anterior.allowed_vlans),
                )
            else:
                return [], None
        else:
            campo = next(iter(campos))
            clave = self._clave_escalar(campos)
            if clave is not None and not self._escalar_a_revertir(clave, anterior, actual_ahora):
                return [], None
            if campo == "description":
                valor = anterior.description or ""
                paso = device.driver.resolver_update_port_description(self.interface, valor)
            elif campo == "admin_up":
                if anterior.admin_up is None:
                    return [], None
                paso = device.driver.resolver_set_port_admin_state(self.interface, bool(anterior.admin_up))
            elif campo == "access_vlan":
                if anterior.access_vlan is None:
                    return [], None
                if anterior.mode == "trunk":
                    paso = device.driver.resolver_set_trunk_pvid_vlan(self.interface, int(anterior.access_vlan))
                else:
                    paso = device.driver.resolver_set_port_access_vlan(self.interface, int(anterior.access_vlan))
            elif campo == "allowed_vlans":
                return self._resolver_rollback_allowed_vlans(anterior, device, actual_ahora)
            elif campo == "poe_enabled":
                if anterior.poe_enabled is None:
                    return [], None
                paso = device.driver.resolver_set_port_poe(self.interface, bool(anterior.poe_enabled))
            elif clave == "storm":
                storm = self._storm_control_a_restaurar(anterior)
                if storm is None:
                    return [], None
                paso = device.driver.resolver_set_storm_control(self.interface, *storm)
            else:
                return [], None

        return [paso], self._verificar_rollback(anterior, campos)

    def _resolver_rollback_reset(self, anterior: "Any", device: "Device") -> "tuple[list, Any]":
        pasos = []
        if anterior.mode == "access" and anterior.access_vlan is not None:
            pasos.append(device.driver.resolver_set_access_mode(
                self.interface, int(anterior.access_vlan),
            ))
        elif anterior.mode == "trunk" and anterior.access_vlan is not None and anterior.allowed_vlans:
            pasos.append(device.driver.resolver_set_trunk_mode(
                self.interface, int(anterior.access_vlan), list(anterior.allowed_vlans),
            ))
        if anterior.description is not None:
            pasos.append(device.driver.resolver_update_port_description(
                self.interface, anterior.description,
            ))
        if anterior.admin_up is not None:
            pasos.append(device.driver.resolver_set_port_admin_state(
                self.interface, bool(anterior.admin_up),
            ))
        storm = self._storm_control_a_restaurar(anterior)
        if storm is not None:
            pasos.append(device.driver.resolver_set_storm_control(self.interface, *storm))

        def verificar(actual):
            if actual is None:
                return False
            comparaciones = (
                ("description", anterior.description),
                ("admin_up", anterior.admin_up),
                ("mode", anterior.mode),
                ("access_vlan", anterior.access_vlan),
                ("storm_control_enabled", anterior.storm_control_enabled),
            )
            for campo_ver, ant_val in comparaciones:
                if ant_val is None:
                    continue
                act_val = getattr(actual, campo_ver, None)
                if act_val is None:
                    continue
                if act_val != ant_val:
                    return False
            if anterior.allowed_vlans:
                if set(actual.allowed_vlans or []) != set(anterior.allowed_vlans):
                    return False
            return True

        return pasos, verificar

    @staticmethod
    def _clave_escalar(campos: "set[str]") -> "str | None":
        if "storm_control_enabled" in campos:
            return "storm"
        if len(campos) == 1:
            campo = next(iter(campos))
            if campo in ("description", "admin_up", "access_vlan"):
                return campo
        return None

    def _escalar_a_revertir(self, clave: str, anterior: "Any", actual_ahora: "Any") -> bool:
        if actual_ahora is None:
            return True
        if clave == "storm":
            return self._storm_a_revertir(anterior, actual_ahora)
        if clave == "description":
            puesta, previa, ahora = (
                self.description or "", anterior.description or "", actual_ahora.description or "",
            )
        elif clave == "admin_up":
            puesta, previa, ahora = self.admin_up, anterior.admin_up, actual_ahora.admin_up
        elif clave == "access_vlan":
            puesta, previa, ahora = self.access_vlan, anterior.access_vlan, actual_ahora.access_vlan
        else:
            return True
        if ahora is None:
            return True
        return debe_revertir_escalar(puesta, previa, ahora)

    def _storm_a_revertir(self, anterior: "Any", ahora: "Any") -> bool:
        if ahora.storm_control_enabled is None:
            return True

        def estado(p: "Any") -> tuple:
            if not p.storm_control_enabled:
                return (False, None)
            return (True, p.storm_control_threshold)

        puesta, previa, actual = estado(self), estado(anterior), estado(ahora)
        if actual != puesta or puesta == previa:
            return False
        if self.storm_control_enabled:
            action = self.storm_control_action or "shutdown"
            trap = self.storm_control_trap if self.storm_control_trap is not None else True
            if ahora.storm_control_action is not None and ahora.storm_control_action != action:
                return False
            if ahora.storm_control_trap is not None and ahora.storm_control_trap != trap:
                return False
        return True

    @staticmethod
    def _storm_control_a_restaurar(
        anterior: "Any",
    ) -> "tuple[bool, float | None, str, bool] | None":
        if anterior.storm_control_enabled is None:
            return None
        if anterior.storm_control_enabled and anterior.storm_control_threshold is None:
            return None
        threshold = (
            int(anterior.storm_control_threshold)
            if anterior.storm_control_threshold is not None else None
        )
        return (
            bool(anterior.storm_control_enabled),
            threshold,
            anterior.storm_control_action or "shutdown",
            anterior.storm_control_trap if anterior.storm_control_trap is not None else True,
        )

    @staticmethod
    def _verificar_rollback(anterior: "Any", campos: "set[str]"):
        def verificar(actual):
            if actual is None:
                return False
            for c in campos:
                if not hasattr(anterior, c):
                    continue
                act_val = getattr(actual, c)
                ant_val = getattr(anterior, c)
                if act_val is None and ant_val is not None:
                    continue
                if act_val != ant_val:
                    return False
            return True
        return verificar

    def ejecutar_rollback(self, pre_state: dict, device: "Device") -> "tuple[bool, Any]":
        if not pre_state.get("existed"):
            return False, None
        anterior = pre_state.get("actual")
        if anterior is None:
            return False, None

        if self.reset:
            return self._ejecutar_rollback_reset(anterior, device)

        campos = self.mutation_fields
        if not self.mode and campos == {"allowed_vlans"}:
            return self._ejecutar_rollback_allowed_vlans(anterior, device)
        if self.mode == "trunk" and self._calcular_trunk_config(anterior) is not None:
            return self._ejecutar_rollback_modo_trunk(anterior, device)
        clave = None if self.mode else self._clave_escalar(campos)
        if clave is not None:
            try:
                ahora = self.reconciliar(device).get("actual")
            except Exception:
                ahora = None
            if not self._escalar_a_revertir(clave, anterior, ahora):
                return False, None
        try:
            if self.mode in ("access", "trunk"):
                if anterior.mode == "access":
                    if anterior.access_vlan is None:
                        return False, None
                    resultado = device.driver.set_access_mode(self.interface, int(anterior.access_vlan), device, device.password)
                elif anterior.mode == "trunk":
                    if anterior.access_vlan is None or not anterior.allowed_vlans:
                        return False, None
                    resultado = device.driver.set_trunk_mode(
                        self.interface, int(anterior.access_vlan), list(anterior.allowed_vlans),
                        device, device.password,
                    )
                else:
                    return False, None
                exitoso = resultado.get("rc", 1) == 0
            elif "storm_control_enabled" in campos:
                if anterior.storm_control_enabled is None:
                    return False, None
                if anterior.storm_control_enabled and anterior.storm_control_threshold is None:
                    return False, None
                resultado = device.driver.set_storm_control(
                    self.interface, bool(anterior.storm_control_enabled), anterior.storm_control_threshold,
                    anterior.storm_control_action or "shutdown",
                    anterior.storm_control_trap if anterior.storm_control_trap is not None else True,
                    device, device.password,
                )
                exitoso = resultado.get("rc", 1) == 0
            else:
                campo = next(iter(campos))
                if campo == "description":
                    valor = anterior.description or ""
                    resultado = device.driver.update_port_description(self.interface, valor, device, device.password)
                    exitoso = resultado.get("rc", 1) == 0
                elif campo == "admin_up":
                    if anterior.admin_up is None:
                        return False, None
                    resultado = device.driver.set_port_admin_state(self.interface, bool(anterior.admin_up), device, device.password)
                    exitoso = resultado.get("rc", 1) == 0
                elif campo == "access_vlan":
                    if anterior.access_vlan is None:
                        return False, None
                    if anterior.mode == "trunk":
                        resultado = device.driver.set_trunk_pvid_vlan(self.interface, int(anterior.access_vlan), device, device.password)
                    else:
                        resultado = device.driver.set_port_access_vlan(self.interface, int(anterior.access_vlan), device, device.password)
                    exitoso = resultado.get("rc", 1) == 0
                elif campo == "poe_enabled":
                    if anterior.poe_enabled is None:
                        return False, None
                    resultado = device.driver.set_port_poe(
                        self.interface, bool(anterior.poe_enabled), device, device.password,
                    )
                    exitoso = resultado.get("rc", 1) == 0
                else:
                    return False, None
        except Exception:
            return True, False

        if not exitoso:
            return True, False

        try:
            puertos = device.driver.list_ports(device, device.password)
            actual = next((p for p in puertos if p.interface == self.interface), None)
            if actual is None:
                verificado = False
            else:
                verificado = True
                for c in campos:
                    if not hasattr(anterior, c):
                        continue
                    act_val = getattr(actual, c)
                    ant_val = getattr(anterior, c)
                    if act_val is None and ant_val is not None:
                        continue
                    if act_val != ant_val:
                        verificado = False
                        break
        except Exception:
            verificado = False
        return True, verificado

    def _ejecutar_rollback_reset(self, anterior: "Any", device: "Device") -> "tuple[bool, Any]":
        ok = True

        def _correr(fn, *args):
            nonlocal ok
            try:
                r = fn(*args, device, device.password)
                if r.get("rc", 1) != 0:
                    ok = False
            except Exception:
                ok = False

        if anterior.mode == "access" and anterior.access_vlan is not None:
            _correr(device.driver.set_access_mode, self.interface, int(anterior.access_vlan))
        elif anterior.mode == "trunk" and anterior.access_vlan is not None and anterior.allowed_vlans:
            _correr(
                device.driver.set_trunk_mode, self.interface,
                int(anterior.access_vlan), list(anterior.allowed_vlans),
            )

        if anterior.description is not None:
            _correr(device.driver.update_port_description, self.interface, anterior.description)

        if anterior.admin_up is not None:
            _correr(device.driver.set_port_admin_state, self.interface, bool(anterior.admin_up))

        storm = self._storm_control_a_restaurar(anterior)
        if storm is not None:
            _correr(device.driver.set_storm_control, self.interface, *storm)

        try:
            puertos = device.driver.list_ports(device, device.password)
            actual = next((p for p in puertos if p.interface == self.interface), None)
            if actual is None:
                return True, False
            verificado = True
            comparaciones = (
                ("description", anterior.description),
                ("admin_up", anterior.admin_up),
                ("mode", anterior.mode),
                ("access_vlan", anterior.access_vlan),
                ("storm_control_enabled", anterior.storm_control_enabled),
            )
            for campo, ant_val in comparaciones:
                if ant_val is None:
                    continue
                act_val = getattr(actual, campo, None)
                if act_val is None:
                    continue
                if act_val != ant_val:
                    verificado = False
                    break
            if verificado and anterior.allowed_vlans:
                actuales = set(actual.allowed_vlans or [])
                if actuales != set(anterior.allowed_vlans):
                    verificado = False
        except Exception:
            verificado = False
        return True, ok and verificado

    def resolver_restore(self, device: "Device", actual_ahora: "Puerto | None" = None) -> "tuple[list, Any]":
        pasos = []
        if self.mode == "access" and self.access_vlan is not None:
            if actual_ahora is None or (
                actual_ahora.mode != "access"
                or actual_ahora.access_vlan != self.access_vlan
            ):
                pasos.append(device.driver.resolver_set_access_mode(
                    self.interface, int(self.access_vlan),
                    viene_de_trunk_con_vlans=_viene_de_trunk_con_vlans(actual_ahora),
                ))
        elif self.mode == "trunk" and self.access_vlan is not None and self.allowed_vlans:
            if (
                actual_ahora is not None
                and actual_ahora.mode == "trunk"
                and actual_ahora.allowed_vlans is not None
            ):
                pvid = int(self.access_vlan) if actual_ahora.access_vlan != self.access_vlan else None
                ahora = set(actual_ahora.allowed_vlans)
                deseadas = set(self.allowed_vlans)
                agregar, quitar = sorted(deseadas - ahora), sorted(ahora - deseadas)
                if pvid is not None or agregar or quitar:
                    pasos.append(device.driver.resolver_set_trunk_config_delta(
                        self.interface, pvid, agregar, quitar,
                    ))
            elif actual_ahora is None or (
                actual_ahora.mode != "trunk"
                or actual_ahora.access_vlan != self.access_vlan
                or set(actual_ahora.allowed_vlans or []) != set(self.allowed_vlans)
            ):
                pasos.append(device.driver.resolver_set_trunk_mode(
                    self.interface, int(self.access_vlan), list(self.allowed_vlans),
                ))
        if self.description is not None:
            if actual_ahora is None or actual_ahora.description != self.description:
                pasos.append(device.driver.resolver_update_port_description(
                    self.interface, self.description,
                ))
        if self.admin_up is not None:
            if actual_ahora is None or actual_ahora.admin_up != self.admin_up:
                pasos.append(device.driver.resolver_set_port_admin_state(
                    self.interface, bool(self.admin_up),
                ))
        storm = self._storm_control_a_restaurar(self)
        if storm is not None:
            enabled, threshold, action, trap = storm
            if actual_ahora is None or (
                actual_ahora.storm_control_enabled != self.storm_control_enabled
                or actual_ahora.storm_control_threshold != self.storm_control_threshold
                or (actual_ahora.storm_control_action or "shutdown") != action
                or (actual_ahora.storm_control_trap if actual_ahora.storm_control_trap is not None else True) != trap
            ):
                pasos.append(device.driver.resolver_set_storm_control(self.interface, *storm))

        def verificar(actual):
            if actual is None:
                return False
            comparaciones = (
                ("description", self.description),
                ("admin_up", self.admin_up),
                ("mode", self.mode),
                ("access_vlan", self.access_vlan),
                ("storm_control_enabled", self.storm_control_enabled),
            )
            for campo, val in comparaciones:
                if val is None:
                    continue
                act_val = getattr(actual, campo, None)
                if act_val is None:
                    continue
                if act_val != val:
                    return False
            if self.allowed_vlans:
                if set(actual.allowed_vlans or []) != set(self.allowed_vlans):
                    return False
            return True

        return pasos, verificar

    def _aplicar_modo_access(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        anterior = pre_state.get("actual") if pre_state else None
        op_key, variant, vars = device.driver.resolver_set_access_mode(
            self.interface, self.access_vlan,
            viene_de_trunk_con_vlans=_viene_de_trunk_con_vlans(anterior),
        )
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "configurar_modo_access"}

    def _aplicar_modo_trunk(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        paso = self._resolver_modo_trunk(device, estado.get("actual"))
        if paso is None:
            return self._noop_resultado("configurar_modo_trunk")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "configurar_modo_trunk"}

    def _calcular_trunk_config(
        self, actual: "Puerto | None",
    ) -> "tuple[list[int], list[int], int | None] | None":
        if actual is None or actual.mode != "trunk" or actual.allowed_vlans is None:
            return None
        previas = set(actual.allowed_vlans)
        deseadas = set(self.allowed_vlans or [])
        pvid = self.access_vlan if actual.access_vlan != self.access_vlan else None
        return sorted(deseadas - previas), sorted(previas - deseadas), pvid

    def _resolver_modo_trunk(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        delta = self._calcular_trunk_config(actual)
        if delta is None:
            return device.driver.resolver_set_trunk_mode(self.interface, self.access_vlan, list(self.allowed_vlans))
        agregar, quitar, pvid = delta
        if not agregar and not quitar and pvid is None:
            return None
        return device.driver.resolver_set_trunk_config_delta(self.interface, pvid, agregar, quitar)

    def _noop_resultado(self, accion: str) -> dict:
        return {"rc": 0, "success": True, "changed": False, "noop": True, "accion": accion}

    def _resolver_description(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.description == self.description:
            return None
        return device.driver.resolver_update_port_description(self.interface, self.description)

    def _aplicar_description(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_description(device, actual)
        if paso is None:
            return self._noop_resultado("actualizar_descripcion_puerto")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "actualizar_descripcion_puerto"}

    def _resolver_admin_up(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.admin_up == self.admin_up:
            return None
        return device.driver.resolver_set_port_admin_state(self.interface, self.admin_up)

    def _aplicar_admin_up(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        accion = "activar_puerto" if self.admin_up else "desactivar_puerto"
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_admin_up(device, actual)
        if paso is None:
            return self._noop_resultado(accion)
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": accion}

    def _resolver_poe(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.poe_enabled == self.poe_enabled:
            return None
        return device.driver.resolver_set_port_poe(self.interface, self.poe_enabled)

    def _aplicar_poe(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        accion = "activar_poe" if self.poe_enabled else "desactivar_poe"
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_poe(device, actual)
        if paso is None:
            return self._noop_resultado(accion)
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": accion}

    def _aplicar_access_vlan(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_access_vlan(device, actual)
        if paso is None:
            return self._noop_resultado("asignar_vlan_acceso")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "asignar_vlan_acceso"}

    def _resolver_access_vlan(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.mode not in ("access", "trunk"):
            raise ValueError(
                f"el puerto {self.interface} no está en modo access ni trunk "
                f"(modo actual: {actual.mode!r}) — no se puede asignar VLAN de acceso"
            )
        if actual is not None and actual.access_vlan == self.access_vlan:
            return None
        if actual is not None and actual.mode == "trunk":
            return device.driver.resolver_set_trunk_pvid_vlan(self.interface, self.access_vlan)
        return device.driver.resolver_set_port_access_vlan(self.interface, self.access_vlan)

    def _aplicar_allowed_vlans(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_allowed_vlans(device, actual)
        if paso is None:
            return self._noop_resultado("configurar_trunk_vlans")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "configurar_trunk_vlans"}

    def _resolver_allowed_vlans(self, device: "Device", actual: "Puerto | None") -> "tuple[str, str | None, dict] | None":
        deseados, agregar, quitar = self._calcular_allowed_vlans(actual)
        if agregar is None:
            return device.driver.resolver_set_trunk_allowed_vlans(self.interface, deseados)
        if not agregar and not quitar:
            return None
        return device.driver.resolver_set_trunk_vlans_delta(self.interface, agregar, quitar)

    def _calcular_allowed_vlans(
        self, actual: "Puerto | None",
    ) -> "tuple[list[int], list[int] | None, list[int] | None]":
        if actual is not None and actual.mode != "trunk":
            raise ValueError(
                f"el puerto {self.interface} no está en modo trunk "
                f"(modo actual: {actual.mode!r}) — no se puede modificar su lista "
                "de VLANs permitidas"
            )
        actuales = actual.allowed_vlans if actual is not None else None

        if self.allowed_vlan_operation == "replace":
            deseados = sorted(set(self.allowed_vlans))
        elif actuales is None:
            raise ValueError(
                f"no se pudo leer la lista de VLANs actual del puerto {self.interface} "
                f"-- no se puede calcular '{self.allowed_vlan_operation}' sin ese estado"
            )
        elif self.allowed_vlan_operation == "add":
            deseados = sorted(set(actuales) | set(self.allowed_vlans))
        elif self.allowed_vlan_operation == "remove":
            deseados = sorted(set(actuales) - set(self.allowed_vlans))
        else:
            raise ValueError(f"allowed_vlan_operation desconocido: {self.allowed_vlan_operation!r}")

        if not deseados:
            raise ValueError(
                f"la operación '{self.allowed_vlan_operation}' dejaría el puerto "
                f"{self.interface} sin VLANs permitidas en el trunk — rechazada"
            )

        if actuales is None:
            return deseados, None, None
        previas = set(actuales)
        finales = set(deseados)
        return deseados, sorted(finales - previas), sorted(previas - finales)

    def _resolver_rollback_allowed_vlans(
        self, anterior: "Puerto", device: "Device", actual_ahora: "Puerto | None",
    ) -> "tuple[list, Any]":
        try:
            _, agregadas, quitadas = self._calcular_allowed_vlans(anterior)
        except ValueError:
            return [], None
        if agregadas is None:
            return [], None

        if actual_ahora is not None and actual_ahora.mode != "trunk":
            return [], None
        if actual_ahora is not None and actual_ahora.allowed_vlans is not None:
            ahora = set(actual_ahora.allowed_vlans)
            quitar = [v for v in agregadas if v in ahora]
            agregar = [v for v in quitadas if v not in ahora]
        else:
            quitar, agregar = list(agregadas), list(quitadas)
        if not quitar and not agregar:
            return [], None

        paso = device.driver.resolver_set_trunk_vlans_delta(self.interface, agregar, quitar)
        return [paso], self._verificar_rollback_allowed_vlans(agregadas, quitadas)

    @staticmethod
    def _verificar_rollback_allowed_vlans(agregadas: "list[int]", quitadas: "list[int]"):
        def verificar(actual):
            if actual is None:
                return False
            if actual.allowed_vlans is None:
                return True
            ahora = set(actual.allowed_vlans)
            return not (set(agregadas) & ahora) and set(quitadas) <= ahora
        return verificar

    def _ejecutar_rollback_allowed_vlans(self, anterior: "Puerto", device: "Device") -> "tuple[bool, Any]":
        return self._ejecutar_rollback_con_plan(
            device, lambda ahora: self._resolver_rollback_allowed_vlans(anterior, device, ahora),
        )

    def _ejecutar_rollback_modo_trunk(self, anterior: "Puerto", device: "Device") -> "tuple[bool, Any]":
        return self._ejecutar_rollback_con_plan(
            device, lambda ahora: self._resolver_rollback_modo_trunk(anterior, device, ahora),
        )

    def _resolver_rollback_modo_trunk(
        self, anterior: "Puerto", device: "Device", actual_ahora: "Puerto | None",
    ) -> "tuple[list, Any]":
        delta = self._calcular_trunk_config(anterior)
        if delta is None:
            return [], None
        agregadas, quitadas, _pvid_aplicado = delta
        restaurar_pvid = anterior.access_vlan is not None and anterior.access_vlan != self.access_vlan

        if actual_ahora is not None:
            if actual_ahora.mode != "trunk":
                return [], None
            if restaurar_pvid and actual_ahora.access_vlan != self.access_vlan:
                restaurar_pvid = False
            if actual_ahora.allowed_vlans is not None:
                ahora = set(actual_ahora.allowed_vlans)
                quitar = [v for v in agregadas if v in ahora]
                agregar = [v for v in quitadas if v not in ahora]
            else:
                quitar, agregar = list(agregadas), list(quitadas)
        else:
            quitar, agregar = list(agregadas), list(quitadas)

        pvid = int(anterior.access_vlan) if restaurar_pvid else None
        if pvid is None and not quitar and not agregar:
            return [], None
        paso = device.driver.resolver_set_trunk_config_delta(self.interface, pvid, agregar, quitar)
        return [paso], self._verificar_rollback_modo_trunk(agregadas, quitadas, pvid)

    @staticmethod
    def _verificar_rollback_modo_trunk(agregadas: "list[int]", quitadas: "list[int]", pvid: "int | None"):
        lista = Puerto._verificar_rollback_allowed_vlans(agregadas, quitadas)

        def verificar(actual):
            if not lista(actual):
                return False
            if pvid is not None and actual.access_vlan is not None and actual.access_vlan != pvid:
                return False
            return True
        return verificar

    def _resolver_storm_control(
        self, device: "Device", actual: "Puerto | None",
    ) -> "tuple[str, str | None, dict] | None":
        action = self.storm_control_action or "shutdown"
        trap = self.storm_control_trap if self.storm_control_trap is not None else True
        if (
            actual is not None
            and actual.storm_control_enabled == self.storm_control_enabled
            and actual.storm_control_threshold == self.storm_control_threshold
            and (actual.storm_control_action or "shutdown") == action
            and (actual.storm_control_trap if actual.storm_control_trap is not None else True) == trap
        ):
            return None
        return device.driver.resolver_set_storm_control(
            self.interface, self.storm_control_enabled, self.storm_control_threshold, action, trap,
        )

    def _aplicar_storm_control(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        accion = "activar_storm_control" if self.storm_control_enabled else "desactivar_storm_control"
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_storm_control(device, actual)
        if paso is None:
            return self._noop_resultado(accion)
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": accion}

    def _aplicar_reset(self, device: "Device") -> dict:
        resultado = device.driver.reset_port(self.interface, device, device.password)
        return {**resultado, "accion": "resetear_puerto"}

    _CAMPOS_ESTADO_CACHE = (
        "description", "admin_up", "access_vlan", "mode", "poe_enabled",
        "storm_control_enabled", "storm_control_threshold", "storm_control_action", "storm_control_trap",
    )

    def campos_de_cache(self) -> "dict | None":
        if self.reset:
            return {}
        cambios = {c: getattr(self, c) for c in self._CAMPOS_ESTADO_CACHE if getattr(self, c) is not None}
        if cambios.get("description") == "":
            cambios["description"] = None
        if cambios.get("storm_control_enabled") is False:
            cambios.update(storm_control_threshold=None, storm_control_action=None, storm_control_trap=None)
        if self.allowed_vlans is not None and (self.mode == "trunk" or self.allowed_vlan_operation == "replace"):
            cambios["allowed_vlans"] = sorted(set(self.allowed_vlans))
        if self.mode == "access":
            cambios["allowed_vlans"] = None
        return cambios

    def repositorio(self) -> str:
        return "puerto"

    def resumen_intento(self) -> str:
        identidad = f"Port {self.interface} on {self.device}" if self.device else f"Port {self.interface}"
        if self.reset:
            return f"Reset {identidad} to defaults"
        campos = self.mutation_fields
        if not campos:
            return f"{identidad}: no changes"
        cambios = ", ".join(f"set {campo} to {getattr(self, campo)!r}" for campo in sorted(campos))
        return f"{identidad}: {cambios}"

    def to_dict(self) -> dict:
        return {
            "interface": self.interface,
            "device": self.device,
            "description": self.description,
            "admin_up": self.admin_up,
            "mode": self.mode,
            "access_vlan": self.access_vlan,
            "allowed_vlans": list(self.allowed_vlans) if self.allowed_vlans is not None else None,
            "allowed_vlan_operation": self.allowed_vlan_operation,
            "poe_enabled": self.poe_enabled,
            "storm_control_enabled": self.storm_control_enabled,
            "storm_control_threshold": self.storm_control_threshold,
            "storm_control_action": self.storm_control_action,
            "storm_control_trap": self.storm_control_trap,
            "reset": self.reset,
            "operational_up": self.operational_up,
            "speed": self.speed,
            "duplex": self.duplex,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Puerto":
        allowed = data.get("allowed_vlans")
        return cls(
            interface=data["interface"],
            device=data.get("device", ""),
            description=data.get("description"),
            admin_up=data.get("admin_up"),
            mode=data.get("mode"),
            access_vlan=data.get("access_vlan"),
            allowed_vlans=list(allowed) if allowed is not None else None,
            allowed_vlan_operation=data.get("allowed_vlan_operation", "add"),
            poe_enabled=data.get("poe_enabled"),
            storm_control_enabled=data.get("storm_control_enabled"),
            storm_control_threshold=data.get("storm_control_threshold"),
            storm_control_action=data.get("storm_control_action"),
            storm_control_trap=data.get("storm_control_trap"),
            reset=data.get("reset", False),
            operational_up=data.get("operational_up"),
            speed=data.get("speed"),
            duplex=data.get("duplex"),
            kind=data.get("kind") or "physical",
        )
