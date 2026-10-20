from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from app.models.rollback_por_estado import RollbackPorPlan, debe_revertir_escalar

if TYPE_CHECKING:
    from app.models.device import Device

_DESCRIPTION_VALID_RE = re.compile(r"^[A-Za-z0-9 .\-]*$")
_MAX_DESCRIPTION_LEN = 240

_MAX_DHCP_RELAY_SERVERS = 8

_MAX_IPV4_SECONDARY = 4


def _validate_vlan_id_range(vlan_id: int) -> None:
    if vlan_id < 1 or vlan_id > 4094:
        raise ValueError(f"VLAN ID {vlan_id} is out of range (1-4094)")


def _validate_description(description: str) -> None:
    if len(description) > _MAX_DESCRIPTION_LEN:
        raise ValueError(f"Description must not exceed {_MAX_DESCRIPTION_LEN} characters")
    if not _DESCRIPTION_VALID_RE.match(description):
        raise ValueError(
            "Description contains invalid characters -- only letters, digits, "
            "spaces, hyphens and periods are allowed"
        )


_MAX_INDICES_GRUPO_RELAY = 20


@dataclass(frozen=True)
class DhcpRelayLayout:
    forma: str
    grupo: "str | None" = None
    indices: "dict[str, int]" = field(default_factory=dict)
    exclusivo: bool = False

    def asignar_indices(
        self, ips: "list[str]", preferidos: "dict[str, int] | None" = None,
    ) -> "dict[str, int]":
        ocupados = set(self.indices.values())
        elegidos: "dict[str, int]" = {}
        for ip in ips:
            pref = (preferidos or {}).get(ip)
            if pref is not None and 0 <= pref < _MAX_INDICES_GRUPO_RELAY and pref not in ocupados:
                indice = pref
            else:
                libres = [i for i in range(_MAX_INDICES_GRUPO_RELAY) if i not in ocupados]
                if not libres:
                    raise ValueError(
                        f"the DHCP relay server group {self.grupo!r} is full "
                        f"({_MAX_INDICES_GRUPO_RELAY} servers)"
                    )
                indice = libres[0]
            ocupados.add(indice)
            elegidos[ip] = indice
        return elegidos


@dataclass
class SVI(RollbackPorPlan):
    vlan_id: int
    device: str = ""
    description: str | None = None
    admin_up: bool | None = None
    ipv4_address: str | None = None
    ipv6_address: str | None = None
    acl_in: str | None = None
    acl_out: str | None = None
    dhcp_relay_add: str | None = None
    dhcp_relay_remove: str | None = None
    ipv4_secondary_add: str | None = None
    ipv4_secondary_remove: str | None = None
    dhcp_relay_servers: list[str] | None = None
    dhcp_relay_layout: "DhcpRelayLayout | None" = field(default=None, compare=False, repr=False)
    ipv4_address_secondary: list[str] | None = None
    eliminar: bool = False
    crear: bool = False
    operational_up: bool | None = None

    def __post_init__(self) -> None:
        _validate_vlan_id_range(self.vlan_id)

    @property
    def mutation_fields(self) -> set[str]:
        campos = ("description", "admin_up", "ipv4_address",
                  "ipv6_address", "acl_in", "acl_out", "dhcp_relay_add", "dhcp_relay_remove",
                  "ipv4_secondary_add", "ipv4_secondary_remove")
        return {c for c in campos if getattr(self, c) is not None}

    def validar(self) -> None:
        if self.eliminar:
            return
        if self.crear:
            if self.description is not None and self.description != "":
                _validate_description(self.description)
            return
        if self.dhcp_relay_add is not None and self.dhcp_relay_remove is not None:
            raise ValueError("cannot set dhcp_relay_add and dhcp_relay_remove in the same call")
        if self.ipv4_secondary_add is not None and self.ipv4_secondary_remove is not None:
            raise ValueError("cannot set ipv4_secondary_add and ipv4_secondary_remove in the same call")
        if not self.mutation_fields:
            raise ValueError(
                "at least one mutation field must be provided "
                "(description, admin_up, ipv4_address, "
                "ipv6_address, acl_in, acl_out, dhcp_relay_add, dhcp_relay_remove, "
                "ipv4_secondary_add, ipv4_secondary_remove, crear, or eliminar)"
            )
        if self.description is not None and self.description != "":
            _validate_description(self.description)

    def reconciliar(self, device: "Device") -> dict:
        interfaces = device.driver.get_svis(device, device.password)
        existente = next((i for i in interfaces if i.vlan_id == self.vlan_id), None)
        return {"existed": existente is not None, "actual": existente}

    @staticmethod
    def reconciliar_lote(recursos: "list[SVI]", device: "Device") -> "list[dict]":
        interfaces = device.driver.get_svis(device, device.password)
        por_vlan = {i.vlan_id: i for i in interfaces}
        return [
            {"existed": r.vlan_id in por_vlan, "actual": por_vlan.get(r.vlan_id)}
            for r in recursos
        ]

    @staticmethod
    def ajustar_estados_lote(recursos: "list[SVI]", estados: "list[dict]") -> "list[dict]":
        ajustados: "list[dict]" = []
        for i, (r, estado) in enumerate(zip(recursos, estados)):
            ipv4_nuevo = None
            ipv6_nuevo = None
            for j, otro in enumerate(recursos):
                if j == i or otro.vlan_id != r.vlan_id:
                    continue
                if otro.ipv4_address:
                    ipv4_nuevo = otro.ipv4_address
                if otro.ipv6_address:
                    ipv6_nuevo = otro.ipv6_address
            if ipv4_nuevo is None and ipv6_nuevo is None:
                ajustados.append(estado)
                continue
            actual = estado.get("actual")
            base = actual if actual is not None else SVI(vlan_id=r.vlan_id)
            actual_efectivo = replace(
                base,
                ipv4_address=ipv4_nuevo if ipv4_nuevo is not None else base.ipv4_address,
                ipv6_address=ipv6_nuevo if ipv6_nuevo is not None else base.ipv6_address,
            )
            ajustados.append({**estado, "actual": actual_efectivo})
        return ajustados

    def resolver_paso(self, device: "Device", actual: "SVI | None") -> "tuple[str, str | None, dict] | None":
        campos = self.mutation_fields
        if len(campos) != 1:
            raise ValueError(
                f"SVI.resolver_paso(): se espera exactamente 1 campo de "
                f"mutación por llamada (se recibieron {sorted(campos)})"
            )
        campo = next(iter(campos))
        if campo == "description":
            return self._resolver_description(device, actual)
        if campo == "admin_up":
            return self._resolver_admin_up(device, actual)
        if campo == "ipv4_address":
            return self._resolver_ipv4(device, actual)
        if campo == "ipv6_address":
            return self._resolver_ipv6(device, actual)
        if campo in ("acl_in", "acl_out"):
            return self._resolver_acl(device, actual, campo)
        if campo == "dhcp_relay_add":
            return self._resolver_dhcp_relay_add(device, actual)
        if campo == "dhcp_relay_remove":
            return self._resolver_dhcp_relay_remove(device, actual)
        if campo == "ipv4_secondary_add":
            return self._resolver_ipv4_secondary_add(device, actual)
        if campo == "ipv4_secondary_remove":
            return self._resolver_ipv4_secondary_remove(device, actual)
        raise ValueError(f"SVI.resolver_paso(): campo no batcheable {campo!r}")

    NECESITA_ESTADO_FRESCO_ROLLBACK = True

    def resolver_rollback(
        self, pre_state: dict, device: "Device", actual_ahora: "SVI | None" = None,
    ) -> "tuple[list, Any]":
        if not pre_state.get("existed"):
            return [], None
        anterior = pre_state.get("actual")
        if anterior is None:
            return [], None

        campos = self.mutation_fields
        if len(campos) != 1:
            return [], None
        campo = next(iter(campos))
        paso = None

        if campo in self._ESCALARES and not self._escalar_a_revertir(campo, anterior, actual_ahora):
            return [], None

        if campo == "description":
            paso = device.driver.resolver_set_svi_description(
                self.vlan_id, anterior.description or "",
            )
        elif campo == "admin_up":
            if anterior.admin_up is None:
                return [], None
            paso = device.driver.resolver_set_svi_admin_state(
                self.vlan_id, bool(anterior.admin_up),
            )
        elif campo == "ipv4_address":
            paso = device.driver.resolver_set_svi_ipv4(self.vlan_id, anterior.ipv4_address)
        elif campo == "ipv4_secondary_add":
            if actual_ahora is None:
                return [], None
            ip_add = self.ipv4_secondary_add
            if ip_add not in (actual_ahora.ipv4_address_secondary or []):
                return [], None
            paso = device.driver.resolver_set_svi_ipv4_secondary(self.vlan_id, None, ip_add)
        elif campo == "ipv4_secondary_remove":
            paso = device.driver.resolver_set_svi_ipv4_secondary(
                self.vlan_id, self.ipv4_secondary_remove, None,
            )
        elif campo == "ipv6_address":
            paso = device.driver.resolver_set_svi_ipv6(self.vlan_id, anterior.ipv6_address)
        elif campo in ("acl_in", "acl_out"):
            return self._resolver_rollback_acl(anterior, device, actual_ahora, campo)
        elif campo in ("dhcp_relay_add", "dhcp_relay_remove"):
            return self._resolver_rollback_dhcp_relay(anterior, device, actual_ahora)
        else:
            return [], None

        def verificar(actual):
            if actual is None:
                return False
            if campo in ("ipv4_secondary_add", "ipv4_secondary_remove"):
                return self._verificar_secundaria(campo, actual)
            return getattr(actual, campo) == getattr(anterior, campo)

        return [paso], verificar

    _ESCALARES = ("description", "admin_up", "ipv4_address", "ipv6_address")

    def _escalar_a_revertir(self, campo: str, anterior: "SVI", actual_ahora: "SVI | None") -> bool:
        if actual_ahora is None:
            return True
        puesta, previa, ahora = getattr(self, campo), getattr(anterior, campo), getattr(actual_ahora, campo)
        if campo == "admin_up":
            if ahora is None:
                return True
        else:
            puesta, previa, ahora = puesta or "", previa or "", ahora or ""
        return debe_revertir_escalar(puesta, previa, ahora)

    def _verificar_secundaria(self, campo: str, actual: "SVI") -> bool:
        secundarias = actual.ipv4_address_secondary or []
        if campo == "ipv4_secondary_add":
            return self.ipv4_secondary_add not in secundarias
        return self.ipv4_secondary_remove in secundarias

    def _resolver_rollback_acl(
        self, anterior: "SVI", device: "Device", actual_ahora: "SVI | None", campo: str,
    ) -> "tuple[list, Any]":
        if actual_ahora is None:
            return [], None
        actual_acl = getattr(actual_ahora, campo)
        previa = getattr(anterior, campo)
        puesta = getattr(self, campo)
        if (previa or None) == (actual_acl or None):
            return [], None
        if (puesta or None) != (actual_acl or None):
            return [], None
        direccion = "in" if campo == "acl_in" else "out"
        paso = device.driver.resolver_set_svi_acl(
            self.vlan_id, direccion, previa, current_acl_name=actual_acl,
        )

        def verificar(actual):
            return actual is not None and (getattr(actual, campo) or None) == (previa or None)

        return [paso], verificar

    def _resolver_rollback_dhcp_relay(
        self, anterior: "SVI", device: "Device", actual_ahora: "SVI | None",
    ) -> "tuple[list, Any]":
        previos = list(anterior.dhcp_relay_servers or [])
        agregar = self.dhcp_relay_add is not None
        ip = self.dhcp_relay_add if agregar else self.dhcp_relay_remove
        if ip is None:
            return [], None
        if agregar == (ip in previos):
            return [], None
        if actual_ahora is not None:
            ahora = list(actual_ahora.dhcp_relay_servers or [])
            if agregar:
                if ip not in ahora:
                    return [], None
                final = [x for x in ahora if x != ip]
            else:
                if ip in ahora:
                    return [], None
                final = ahora + [ip]
        else:
            final = previos
        layout = actual_ahora.dhcp_relay_layout if actual_ahora is not None else None
        previo = anterior.dhcp_relay_layout
        preferidos = dict(previo.indices) if previo is not None else None
        if agregar:
            paso = device.driver.resolver_set_svi_dhcp_relay_delta(
                self.vlan_id, [], [ip], final, layout=layout, indices_previos=preferidos,
            )
        else:
            paso = device.driver.resolver_set_svi_dhcp_relay_delta(
                self.vlan_id, [ip], [], final, layout=layout, indices_previos=preferidos,
            )

        def verificar(actual):
            if actual is None:
                return False
            presente = ip in (actual.dhcp_relay_servers or [])
            return (not presente) if agregar else presente

        return [paso], verificar

    def aplicar(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        if self.eliminar:
            estado = pre_state if pre_state is not None else self.reconciliar(device)
            if not estado["existed"]:
                return {"rc": 0, "success": True, "changed": False, "noop": True, "accion": "eliminar_svi"}
            resultado = device.driver.delete_svi(self.vlan_id, device, device.password)
            return {**resultado, "accion": "eliminar_svi"}

        if self.crear:
            return self._aplicar_crear(device, pre_state)

        campos = self.mutation_fields
        if len(campos) != 1:
            raise ValueError(
                f"SVI.aplicar(): se espera exactamente 1 campo de "
                f"mutación por llamada (se recibieron {sorted(campos)}) -- "
                f"un endpoint por campo, mismo criterio que Puerto"
            )
        campo = next(iter(campos))
        if campo == "description":
            return self._aplicar_description(device, pre_state)
        if campo == "admin_up":
            return self._aplicar_admin_up(device, pre_state)
        if campo == "ipv4_address":
            return self._aplicar_ipv4(device, pre_state)
        if campo == "ipv6_address":
            return self._aplicar_ipv6(device, pre_state)
        if campo in ("acl_in", "acl_out"):
            return self._aplicar_acl(device, pre_state, campo)
        if campo == "dhcp_relay_add":
            return self._aplicar_dhcp_relay_add(device, pre_state)
        if campo == "dhcp_relay_remove":
            return self._aplicar_dhcp_relay_remove(device, pre_state)
        if campo == "ipv4_secondary_add":
            return self._aplicar_ipv4_secondary_add(device, pre_state)
        if campo == "ipv4_secondary_remove":
            return self._aplicar_ipv4_secondary_remove(device, pre_state)
        raise ValueError(f"SVI.aplicar(): no hay driver call para el campo {campo!r}")

    def _noop_resultado(self, accion: str, **extra: object) -> dict:
        return {"rc": 0, "success": True, "changed": False, "noop": True, "accion": accion, **extra}

    def _aplicar_crear(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        if estado["existed"]:
            return self._noop_resultado("crear_svi", duplicate=True)
        resultado = device.driver.create_svi(self.vlan_id, device, device.password)
        if not resultado.get("success") or not self.description:
            return {**resultado, "accion": "crear_svi"}
        desc_resultado = device.driver.set_svi_description(
            self.vlan_id, self.description, device, device.password,
        )
        return {**desc_resultado, "accion": "crear_svi"}

    def _resolver_description(self, device: "Device", actual: "SVI | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.description == self.description:
            return None
        return device.driver.resolver_set_svi_description(self.vlan_id, self.description)

    def _aplicar_description(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_description(device, actual)
        if paso is None:
            return self._noop_resultado("actualizar_descripcion_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "actualizar_descripcion_svi"}

    def _resolver_admin_up(self, device: "Device", actual: "SVI | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.admin_up == self.admin_up:
            return None
        return device.driver.resolver_set_svi_admin_state(self.vlan_id, self.admin_up)

    def _aplicar_admin_up(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        accion = "activar_svi" if self.admin_up else "desactivar_svi"
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_admin_up(device, actual)
        if paso is None:
            return self._noop_resultado(accion)
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": accion}

    def _resolver_ipv4(self, device: "Device", actual: "SVI | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.ipv4_address == self.ipv4_address:
            return None
        return device.driver.resolver_set_svi_ipv4(self.vlan_id, self.ipv4_address)

    def _aplicar_ipv4(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_ipv4(device, actual)
        if paso is None:
            return self._noop_resultado("configurar_ipv4_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "configurar_ipv4_svi"}

    def _resolver_ipv4_secondary_add(
        self, device: "Device", actual: "SVI | None",
    ) -> "tuple[str, str | None, dict] | None":
        secundarias_actuales = list(actual.ipv4_address_secondary) if actual and actual.ipv4_address_secondary else []
        ip = self.ipv4_secondary_add
        if not (actual and actual.ipv4_address):
            raise ValueError(
                "cannot add a secondary IPv4 address: interface has no primary IPv4 address configured"
            )
        if ip in secundarias_actuales:
            return None
        if len(secundarias_actuales) >= _MAX_IPV4_SECONDARY:
            raise ValueError(f"cannot add secondary IPv4 address: limit of {_MAX_IPV4_SECONDARY} reached")
        return device.driver.resolver_set_svi_ipv4_secondary(self.vlan_id, ip, None)

    def _aplicar_ipv4_secondary_add(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_ipv4_secondary_add(device, actual)
        if paso is None:
            return self._noop_resultado("agregar_ipv4_secundaria_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "agregar_ipv4_secundaria_svi"}

    def _resolver_ipv4_secondary_remove(
        self, device: "Device", actual: "SVI | None",
    ) -> "tuple[str, str | None, dict] | None":
        secundarias_actuales = list(actual.ipv4_address_secondary) if actual and actual.ipv4_address_secondary else []
        ip = self.ipv4_secondary_remove
        if ip not in secundarias_actuales:
            return None
        return device.driver.resolver_set_svi_ipv4_secondary(self.vlan_id, None, ip)

    def _aplicar_ipv4_secondary_remove(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_ipv4_secondary_remove(device, actual)
        if paso is None:
            return self._noop_resultado("eliminar_ipv4_secundaria_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "eliminar_ipv4_secundaria_svi"}

    def _resolver_ipv6(self, device: "Device", actual: "SVI | None") -> "tuple[str, str | None, dict] | None":
        if actual is not None and actual.ipv6_address == self.ipv6_address:
            return None
        return device.driver.resolver_set_svi_ipv6(self.vlan_id, self.ipv6_address)

    def _aplicar_ipv6(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_ipv6(device, actual)
        if paso is None:
            return self._noop_resultado("configurar_ipv6_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "configurar_ipv6_svi"}

    def _resolver_acl(
        self, device: "Device", actual: "SVI | None", campo: str = "acl_in",
    ) -> "tuple[str, str | None, dict] | None":
        direccion = "in" if campo == "acl_in" else "out"
        valor = self.acl_in if campo == "acl_in" else self.acl_out
        actual_valor = getattr(actual, campo) if actual is not None else None
        if actual is not None and (actual_valor or None) == (valor or None):
            return None
        return device.driver.resolver_set_svi_acl(self.vlan_id, direccion, valor, current_acl_name=actual_valor)

    def _aplicar_acl(self, device: "Device", pre_state: "dict | None" = None, campo: str = "acl_in") -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_acl(device, actual, campo)
        if paso is None:
            return self._noop_resultado("configurar_acl_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "configurar_acl_svi"}

    @staticmethod
    def _es_ipv6(ip: str) -> bool:
        return ":" in ip

    def _resolver_dhcp_relay_add(
        self, device: "Device", actual: "SVI | None",
    ) -> "tuple[str, str | None, dict] | None":
        servers_actuales = list(actual.dhcp_relay_servers) if actual and actual.dhcp_relay_servers else []
        ip = self.dhcp_relay_add
        if self._es_ipv6(ip):
            if not (actual and actual.ipv6_address):
                raise ValueError(
                    "cannot add an IPv6 DHCP relay server: interface has no IPv6 address configured"
                )
        elif not (actual and actual.ipv4_address):
            raise ValueError(
                "cannot add an IPv4 DHCP relay server: interface has no IPv4 address configured"
            )
        if ip in servers_actuales:
            return None
        if len(servers_actuales) >= _MAX_DHCP_RELAY_SERVERS:
            raise ValueError(f"cannot add DHCP relay server: limit of {_MAX_DHCP_RELAY_SERVERS} reached")
        return device.driver.resolver_set_svi_dhcp_relay_delta(
            self.vlan_id, [ip], [], servers_actuales + [ip],
            layout=actual.dhcp_relay_layout if actual is not None else None,
        )

    def _aplicar_dhcp_relay_add(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_dhcp_relay_add(device, actual)
        if paso is None:
            return self._noop_resultado("agregar_dhcp_relay_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "agregar_dhcp_relay_svi"}

    def _resolver_dhcp_relay_remove(
        self, device: "Device", actual: "SVI | None",
    ) -> "tuple[str, str | None, dict] | None":
        servers_actuales = list(actual.dhcp_relay_servers) if actual and actual.dhcp_relay_servers else []
        ip = self.dhcp_relay_remove
        if ip not in servers_actuales:
            return None
        return device.driver.resolver_set_svi_dhcp_relay_delta(
            self.vlan_id, [], [ip], [s for s in servers_actuales if s != ip],
            layout=actual.dhcp_relay_layout if actual is not None else None,
        )

    def _aplicar_dhcp_relay_remove(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        paso = self._resolver_dhcp_relay_remove(device, actual)
        if paso is None:
            return self._noop_resultado("eliminar_dhcp_relay_svi")
        op_key, variant, vars = paso
        resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
        return {**resultado, "accion": "eliminar_dhcp_relay_svi"}

    def ejecutar_rollback(self, pre_state: dict, device: "Device") -> "tuple[bool, Any]":
        if not pre_state.get("existed"):
            return False, None
        anterior = pre_state.get("actual")
        if anterior is None:
            return False, None

        campos = self.mutation_fields
        if len(campos) != 1:
            return False, None
        campo = next(iter(campos))
        if campo in self._ESCALARES:
            try:
                ahora = self.reconciliar(device).get("actual")
            except Exception:
                ahora = None
            if not self._escalar_a_revertir(campo, anterior, ahora):
                return False, None
        try:
            if campo == "description":
                resultado = device.driver.set_svi_description(
                    self.vlan_id, anterior.description or "", device, device.password,
                )
            elif campo == "admin_up":
                if anterior.admin_up is None:
                    return False, None
                resultado = device.driver.set_svi_admin_state(
                    self.vlan_id, bool(anterior.admin_up), device, device.password,
                )
            elif campo == "ipv4_address":
                resultado = device.driver.set_svi_ipv4(
                    self.vlan_id, anterior.ipv4_address, device, device.password,
                )
            elif campo == "ipv4_secondary_add":
                ip = self.ipv4_secondary_add
                actual_ahora = self.reconciliar(device).get("actual")
                esta_ahora = actual_ahora is not None and ip in (actual_ahora.ipv4_address_secondary or [])
                if not esta_ahora:
                    return False, None
                resultado = device.driver.set_svi_ipv4_secondary(
                    self.vlan_id, None, ip, device, device.password,
                )
            elif campo == "ipv4_secondary_remove":
                resultado = device.driver.set_svi_ipv4_secondary(
                    self.vlan_id, self.ipv4_secondary_remove, None, device, device.password,
                )
            elif campo == "ipv6_address":
                resultado = device.driver.set_svi_ipv6(
                    self.vlan_id, anterior.ipv6_address, device, device.password,
                )
            elif campo in ("acl_in", "acl_out"):
                return self._ejecutar_rollback_con_plan(
                    device, lambda ahora: self._resolver_rollback_acl(anterior, device, ahora, campo),
                )
            elif campo in ("dhcp_relay_add", "dhcp_relay_remove"):
                return self._ejecutar_rollback_con_plan(
                    device, lambda ahora: self._resolver_rollback_dhcp_relay(anterior, device, ahora),
                )
            else:
                return False, None
            exitoso = resultado.get("rc", 1) == 0
        except Exception:
            return True, False

        if not exitoso:
            return True, False

        try:
            actual_final = self.reconciliar(device).get("actual")
            if actual_final is None:
                verificado = False
            elif campo in ("ipv4_secondary_add", "ipv4_secondary_remove"):
                verificado = self._verificar_secundaria(campo, actual_final)
            else:
                verificado = getattr(actual_final, campo) == getattr(anterior, campo)
        except Exception:
            verificado = False
        return True, verificado

    def resolver_restore(self, device: "Device", actual_ahora: "SVI | None" = None) -> "tuple[list, Any]":
        pasos = []
        if self.description is not None:
            if actual_ahora is None or actual_ahora.description != self.description:
                pasos.append(device.driver.resolver_set_svi_description(
                    self.vlan_id, self.description,
                ))
        if self.admin_up is not None:
            if actual_ahora is None or actual_ahora.admin_up != self.admin_up:
                pasos.append(device.driver.resolver_set_svi_admin_state(
                    self.vlan_id, bool(self.admin_up),
                ))
        if self.ipv4_address is not None:
            if actual_ahora is None or actual_ahora.ipv4_address != self.ipv4_address:
                pasos.append(device.driver.resolver_set_svi_ipv4(
                    self.vlan_id, self.ipv4_address,
                ))
        if self.ipv6_address is not None:
            if actual_ahora is None or actual_ahora.ipv6_address != self.ipv6_address:
                pasos.append(device.driver.resolver_set_svi_ipv6(
                    self.vlan_id, self.ipv6_address,
                ))
        if self.dhcp_relay_servers:
            if actual_ahora is None:
                pasos.append(device.driver.resolver_set_svi_dhcp_relay(
                    self.vlan_id, list(self.dhcp_relay_servers),
                ))
            elif set(actual_ahora.dhcp_relay_servers or []) != set(self.dhcp_relay_servers):
                ahora = list(actual_ahora.dhcp_relay_servers or [])
                pasos.append(device.driver.resolver_set_svi_dhcp_relay_delta(
                    self.vlan_id,
                    [x for x in self.dhcp_relay_servers if x not in ahora],
                    [x for x in ahora if x not in self.dhcp_relay_servers],
                    list(self.dhcp_relay_servers),
                    layout=actual_ahora.dhcp_relay_layout,
                ))
        if actual_ahora is not None:
            if self.ipv4_address_secondary is not None:
                if actual_ahora.ipv4_address_secondary != self.ipv4_address_secondary:
                    pasos.append(device.driver.resolver_set_svi_ipv4_secondary(
                        self.vlan_id, self.ipv4_address_secondary,
                        actual_ahora.ipv4_address_secondary,
                    ))
            if self.acl_in is not None:
                if (actual_ahora.acl_in or None) != (self.acl_in or None):
                    pasos.append(device.driver.resolver_set_svi_acl(
                        self.vlan_id, "in", self.acl_in,
                        current_acl_name=actual_ahora.acl_in,
                    ))
            if self.acl_out is not None:
                if (actual_ahora.acl_out or None) != (self.acl_out or None):
                    pasos.append(device.driver.resolver_set_svi_acl(
                        self.vlan_id, "out", self.acl_out,
                        current_acl_name=actual_ahora.acl_out,
                    ))

        def verificar(actual):
            if actual is None:
                return False
            comparaciones = (
                ("description", self.description),
                ("admin_up", self.admin_up),
                ("ipv4_address", self.ipv4_address),
                ("ipv6_address", self.ipv6_address),
                ("acl_in", self.acl_in),
                ("acl_out", self.acl_out),
            )
            for campo, val in comparaciones:
                if val is None:
                    continue
                if getattr(actual, campo, None) != val:
                    return False
            if self.dhcp_relay_servers:
                if set(actual.dhcp_relay_servers or []) != set(self.dhcp_relay_servers):
                    return False
            if self.ipv4_address_secondary is not None:
                if actual.ipv4_address_secondary != self.ipv4_address_secondary:
                    return False
            return True

        return pasos, verificar

    def campos_de_cache(self) -> "dict | None":
        if self.crear or self.eliminar:
            return None
        cambios = {}
        for campo in ("description", "admin_up", "ipv4_address", "ipv6_address", "acl_in", "acl_out"):
            valor = getattr(self, campo)
            if valor is not None:
                cambios[campo] = None if valor == "" else valor
        return cambios

    def repositorio(self) -> str:
        return "svi"

    def resumen_intento(self) -> str:
        identidad = f"SVI {self.vlan_id} on {self.device}" if self.device else f"SVI {self.vlan_id}"
        if self.eliminar:
            return f"Delete {identidad}"
        if self.crear:
            return f"Create {identidad}"
        campos = self.mutation_fields
        if not campos:
            return f"{identidad}: no changes"
        cambios = ", ".join(f"set {campo} to {getattr(self, campo)!r}" for campo in sorted(campos))
        return f"{identidad}: {cambios}"

    def to_dict(self) -> dict:
        return {
            "vlan_id": self.vlan_id,
            "device": self.device,
            "description": self.description,
            "admin_up": self.admin_up,
            "ipv4_address": self.ipv4_address,
            "ipv4_address_secondary": (
                list(self.ipv4_address_secondary) if self.ipv4_address_secondary is not None else None
            ),
            "ipv6_address": self.ipv6_address,
            "acl_in": self.acl_in,
            "acl_out": self.acl_out,
            "dhcp_relay_servers": list(self.dhcp_relay_servers) if self.dhcp_relay_servers is not None else None,
            "operational_up": self.operational_up,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SVI":
        servers = data.get("dhcp_relay_servers")
        secundarias = data.get("ipv4_address_secondary")
        return cls(
            vlan_id=data["vlan_id"],
            device=data.get("device", ""),
            description=data.get("description"),
            admin_up=data.get("admin_up"),
            ipv4_address=data.get("ipv4_address"),
            ipv4_address_secondary=list(secundarias) if secundarias is not None else None,
            ipv6_address=data.get("ipv6_address"),
            acl_in=data.get("acl_in"),
            acl_out=data.get("acl_out"),
            dhcp_relay_servers=list(servers) if servers is not None else None,
            operational_up=data.get("operational_up"),
        )
