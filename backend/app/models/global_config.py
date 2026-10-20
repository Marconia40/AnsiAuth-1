from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from app.models.rollback_por_estado import debe_revertir_escalar

if TYPE_CHECKING:
    from app.models.device import Device

_HOSTNAME_VALID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _validate_hostname(hostname: str) -> None:
    if not _HOSTNAME_VALID_RE.match(hostname):
        raise ValueError(
            "Hostname must be alphanumeric (hyphens allowed in the middle), "
            "1-63 characters, and not start or end with a hyphen"
        )


@dataclass
class GlobalConfig:
    device: str = ""
    PERSISTE_EN_CACHE: ClassVar[bool] = False

    hostname: str | None = None
    snmp_config: dict | None = None
    snmp_trap_host_remove: dict | None = None
    route_add: dict | None = None
    route_remove: dict | None = None
    ntp_server_add: dict | None = None
    ntp_server_remove: dict | None = None
    dns_server_add: dict | None = None
    dns_server_remove: dict | None = None
    dns_domain_set: str | None = None
    log_server_add: dict | None = None
    log_server_remove: dict | None = None
    acl_create: dict | None = None
    acl_rule_remove: dict | None = None
    acl_delete: str | None = None
    running_config: str | None = None
    device_version: str | None = None
    snmp_enabled: bool | None = None
    snmp_version: str | None = None
    snmp_community: str | None = None
    snmp_permission: str | None = None
    snmp_trap_hosts: list[str] | None = None
    snmp_acl_name: str | None = None
    ntp_servers: list[str] | None = None
    dns_servers: list[str] | None = None
    log_servers: list[str] | None = None
    log_level: str | None = None
    routes: list[dict] | None = None
    acls: list[dict] | None = None

    @property
    def mutation_fields(self) -> set[str]:
        campos = (
            "hostname", "snmp_config", "snmp_trap_host_remove", "route_add", "route_remove",
            "ntp_server_add", "ntp_server_remove", "dns_server_add", "dns_server_remove",
            "dns_domain_set", "log_server_add", "log_server_remove",
            "acl_create", "acl_rule_remove", "acl_delete",
        )
        return {c for c in campos if getattr(self, c) is not None}

    def validar(self) -> None:
        if not self.mutation_fields:
            raise ValueError(
                "at least one mutation field must be provided "
                "(hostname, snmp_config, snmp_trap_host_remove, route_add, route_remove, ntp_server_add, "
                "ntp_server_remove, dns_server_add, dns_server_remove, dns_domain_set, "
                "log_server_add, log_server_remove, acl_create, acl_rule_remove, acl_delete)"
            )
        if self.hostname is not None:
            _validate_hostname(self.hostname)
        if self.snmp_config is not None:
            claves_validas = {"version", "community", "trap_source", "trap_host", "trap_version"}
            desconocidas = set(self.snmp_config) - claves_validas
            if desconocidas:
                raise ValueError(f"snmp_config: unknown keys {sorted(desconocidas)} (valid: {sorted(claves_validas)})")
            if not any(self.snmp_config.get(c) is not None for c in claves_validas):
                raise ValueError(f"snmp_config: at least one of {sorted(claves_validas)} must be provided")
            trap_host, trap_version = self.snmp_config.get("trap_host"), self.snmp_config.get("trap_version")
            if (trap_host is None) != (trap_version is None):
                raise ValueError("snmp_config: 'trap_host' and 'trap_version' must be provided together")
        if self.snmp_trap_host_remove is not None:
            desconocidas = set(self.snmp_trap_host_remove) - {"host", "community"}
            if desconocidas:
                raise ValueError(
                    f"snmp_trap_host_remove: unknown keys {sorted(desconocidas)} (valid: ['host', 'community'])"
                )
            if not self.snmp_trap_host_remove.get("host"):
                raise ValueError("snmp_trap_host_remove: 'host' is required")
            if not self.snmp_trap_host_remove.get("community"):
                raise ValueError("snmp_trap_host_remove: 'community' is required")
        if self.log_server_add is not None:
            desconocidas = set(self.log_server_add) - {"server", "level"}
            if desconocidas:
                raise ValueError(f"log_server_add: unknown keys {sorted(desconocidas)} (valid: ['server', 'level'])")
            if not self.log_server_add.get("server"):
                raise ValueError("log_server_add: 'server' is required")
        if self.log_server_remove is not None:
            desconocidas = set(self.log_server_remove) - {"server"}
            if desconocidas:
                raise ValueError(f"log_server_remove: unknown keys {sorted(desconocidas)} (valid: ['server'])")
            if not self.log_server_remove.get("server"):
                raise ValueError("log_server_remove: 'server' is required")
        if self.route_add is not None:
            self._validar_route_dict("route_add", self.route_add)
        if self.route_remove is not None:
            self._validar_route_dict("route_remove", self.route_remove)
        if self.ntp_server_add is not None:
            desconocidas = set(self.ntp_server_add) - {"server", "prefer"}
            if desconocidas:
                raise ValueError(f"ntp_server_add: unknown keys {sorted(desconocidas)} (valid: ['server', 'prefer'])")
            if not self.ntp_server_add.get("server"):
                raise ValueError("ntp_server_add: 'server' is required")
        if self.ntp_server_remove is not None:
            desconocidas = set(self.ntp_server_remove) - {"server"}
            if desconocidas:
                raise ValueError(f"ntp_server_remove: unknown keys {sorted(desconocidas)} (valid: ['server'])")
            if not self.ntp_server_remove.get("server"):
                raise ValueError("ntp_server_remove: 'server' is required")
        if self.dns_server_add is not None:
            desconocidas = set(self.dns_server_add) - {"server"}
            if desconocidas:
                raise ValueError(f"dns_server_add: unknown keys {sorted(desconocidas)} (valid: ['server'])")
            if not self.dns_server_add.get("server"):
                raise ValueError("dns_server_add: 'server' is required")
        if self.dns_server_remove is not None:
            desconocidas = set(self.dns_server_remove) - {"server"}
            if desconocidas:
                raise ValueError(f"dns_server_remove: unknown keys {sorted(desconocidas)} (valid: ['server'])")
            if not self.dns_server_remove.get("server"):
                raise ValueError("dns_server_remove: 'server' is required")
        if self.dns_domain_set is not None and not self.dns_domain_set.strip():
            raise ValueError("dns_domain_set: must not be empty")
        if self.acl_create is not None:
            self._validar_acl_dict("acl_create", self.acl_create)
        if self.acl_rule_remove is not None:
            self._validar_acl_dict("acl_rule_remove", self.acl_rule_remove)
        if self.acl_delete is not None and not self.acl_delete.strip():
            raise ValueError("acl_delete: must not be empty")

    @staticmethod
    def _validar_acl_dict(nombre_campo: str, valor: dict) -> None:
        claves_validas = {"name", "rules"}
        desconocidas = set(valor) - claves_validas
        if desconocidas:
            raise ValueError(f"{nombre_campo}: unknown keys {sorted(desconocidas)} (valid: {sorted(claves_validas)})")
        if not valor.get("name"):
            raise ValueError(f"{nombre_campo}: 'name' is required")
        if not valor.get("rules"):
            raise ValueError(f"{nombre_campo}: 'rules' must be a non-empty list")

    @staticmethod
    def _validar_route_dict(nombre_campo: str, valor: dict) -> None:
        claves_validas = {"destination", "next_hop"}
        desconocidas = set(valor) - claves_validas
        if desconocidas:
            raise ValueError(f"{nombre_campo}: unknown keys {sorted(desconocidas)} (valid: {sorted(claves_validas)})")
        faltantes = claves_validas - {c for c in claves_validas if valor.get(c)}
        if faltantes:
            raise ValueError(f"{nombre_campo}: missing required keys {sorted(faltantes)}")
        try:
            ipaddress.ip_network(valor["destination"], strict=False)
        except ValueError as exc:
            raise ValueError(f"{nombre_campo}: invalid 'destination' ({exc})")
        try:
            ipaddress.ip_address(valor["next_hop"])
        except ValueError as exc:
            raise ValueError(f"{nombre_campo}: invalid 'next_hop' ({exc})")

    def reconciliar(self, device: "Device") -> dict:
        actual = device.driver.get_global_config(device, device.password)
        return {"existed": actual is not None, "actual": actual}

    def aplicar(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        campos = self.mutation_fields
        if len(campos) != 1:
            raise ValueError(
                f"GlobalConfig.aplicar(): se espera exactamente 1 campo de "
                f"mutación por llamada (se recibieron {sorted(campos)}) -- "
                f"un endpoint por campo, mismo criterio que SVI/Puerto"
            )
        campo = next(iter(campos))
        if campo == "hostname":
            return self._aplicar_hostname(device, pre_state)
        if campo == "snmp_config":
            return self._aplicar_snmp_config(device, pre_state)
        if campo == "snmp_trap_host_remove":
            return self._aplicar_snmp_trap_host_remove(device, pre_state)
        if campo == "route_add":
            return self._aplicar_route_add(device, pre_state)
        if campo == "route_remove":
            return self._aplicar_route_remove(device, pre_state)
        if campo == "ntp_server_add":
            return self._aplicar_ntp_add(device)
        if campo == "ntp_server_remove":
            return self._aplicar_ntp_remove(device)
        if campo == "dns_server_add":
            return self._aplicar_dns_add(device)
        if campo == "dns_server_remove":
            return self._aplicar_dns_remove(device)
        if campo == "dns_domain_set":
            return self._aplicar_dns_domain(device)
        if campo == "log_server_add":
            return self._aplicar_log_server_add(device)
        if campo == "log_server_remove":
            return self._aplicar_log_server_remove(device)
        if campo == "acl_create":
            return self._aplicar_acl_create(device, pre_state)
        if campo == "acl_rule_remove":
            return self._aplicar_acl_rule_remove(device, pre_state)
        if campo == "acl_delete":
            return self._aplicar_acl_delete(device)
        raise ValueError(f"GlobalConfig.aplicar(): no hay driver call para el campo {campo!r} todavía")

    def _noop_resultado(self, accion: str, **extra: object) -> dict:
        return {"rc": 0, "success": True, "changed": False, "noop": True, "accion": accion, **extra}

    def _aplicar_hostname(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        if actual is not None and actual.hostname == self.hostname:
            return self._noop_resultado("modificar_hostname")
        resultado = device.driver.set_hostname(self.hostname, device, device.password)
        return {**resultado, "accion": "modificar_hostname"}

    def _aplicar_snmp_config(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        cambios = {}
        version = self.snmp_config.get("version")
        if version is not None and version != (actual.snmp_version if actual is not None else None):
            cambios["version"] = version
        community = self.snmp_config.get("community")
        if community is not None and community != (actual.snmp_community if actual is not None else None):
            cambios["community"] = community
        trap_source = self.snmp_config.get("trap_source")
        if trap_source is not None:
            cambios["trap_source"] = trap_source
        trap_host, trap_version = self.snmp_config.get("trap_host"), self.snmp_config.get("trap_version")
        if trap_host is not None:
            community_para_trap = community or (actual.snmp_community if actual is not None else None)
            if not community_para_trap:
                raise ValueError(
                    "snmp_config: 'trap_host' requires a resolvable community "
                    "(either in this same request or already configured on the device)"
                )
            cambios["trap_host"] = trap_host
            cambios["trap_version"] = trap_version
            cambios["trap_host_community"] = community_para_trap
        if not cambios:
            return self._noop_resultado("configurar_snmp")
        resultado = device.driver.set_snmp(cambios, device, device.password)
        return {**resultado, "accion": "configurar_snmp"}

    def _aplicar_snmp_trap_host_remove(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        host = self.snmp_trap_host_remove["host"]
        community = self.snmp_trap_host_remove["community"]
        resultado = device.driver.remove_snmp_trap_host(host, device, device.password, community=community)
        return {**resultado, "accion": "sacar_snmp_trap_host"}

    def _aplicar_log_server_add(self, device: "Device") -> dict:
        resultado = device.driver.add_log_server(
            self.log_server_add["server"], self.log_server_add.get("level"), device, device.password,
        )
        return {**resultado, "accion": "agregar_log_server"}

    def _aplicar_log_server_remove(self, device: "Device") -> dict:
        resultado = device.driver.remove_log_server(self.log_server_remove["server"], device, device.password)
        return {**resultado, "accion": "eliminar_log_server"}

    def _aplicar_route_add(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        destino_normalizado = str(ipaddress.ip_network(self.route_add["destination"], strict=False))
        next_hop = self.route_add["next_hop"]
        rutas_actuales = (actual.routes if actual is not None else None) or []
        existente = next((r for r in rutas_actuales if r.get("destination") == destino_normalizado), None)
        if existente is not None:
            if existente.get("next_hop") == next_hop:
                return self._noop_resultado("agregar_ruta")
            return {
                "rc": 0, "success": True, "changed": False, "accion": "ruta_ya_existe",
                "destination": destino_normalizado, "next_hop_actual": existente.get("next_hop"),
            }
        resultado = device.driver.set_route(destino_normalizado, next_hop, device, device.password)
        return {**resultado, "accion": "agregar_ruta"}

    def _aplicar_route_remove(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        destino_normalizado = str(ipaddress.ip_network(self.route_remove["destination"], strict=False))
        next_hop = self.route_remove["next_hop"]
        rutas_actuales = (actual.routes if actual is not None else None) or []
        existente = next(
            (r for r in rutas_actuales if r.get("destination") == destino_normalizado and r.get("next_hop") == next_hop),
            None,
        )
        if existente is None:
            return self._noop_resultado("eliminar_ruta")
        resultado = device.driver.remove_route(destino_normalizado, next_hop, device, device.password)
        return {**resultado, "accion": "eliminar_ruta"}

    def _aplicar_ntp_add(self, device: "Device") -> dict:
        resultado = device.driver.add_ntp_server(
            self.ntp_server_add["server"], self.ntp_server_add.get("prefer") or False, device, device.password,
        )
        return {**resultado, "accion": "agregar_ntp"}

    def _aplicar_ntp_remove(self, device: "Device") -> dict:
        resultado = device.driver.remove_ntp_server(self.ntp_server_remove["server"], device, device.password)
        return {**resultado, "accion": "eliminar_ntp"}

    def _aplicar_dns_add(self, device: "Device") -> dict:
        resultado = device.driver.add_dns_server(self.dns_server_add["server"], device, device.password)
        return {**resultado, "accion": "agregar_dns"}

    def _aplicar_dns_remove(self, device: "Device") -> dict:
        resultado = device.driver.remove_dns_server(self.dns_server_remove["server"], device, device.password)
        return {**resultado, "accion": "eliminar_dns"}

    def _aplicar_dns_domain(self, device: "Device") -> dict:
        resultado = device.driver.set_dns_domain(self.dns_domain_set, device, device.password)
        return {**resultado, "accion": "configurar_dns_domain"}

    @staticmethod
    def _reglas_acl_actuales(actual: "GlobalConfig | None", name: str) -> list[str]:
        if actual is None or not actual.acls:
            return []
        acl = next((a for a in actual.acls if a.get("name") == name), None)
        return acl.get("rules", []) if acl is not None else []

    _SUFIJO_CONTADOR_RE = re.compile(r"\s*\((?:\d+ matches?|\d+ times? matched)\)\s*$", re.IGNORECASE)

    @classmethod
    def _regla_ya_presente(cls, regla_formateada: str, reglas_actuales: list[str]) -> bool:
        return any(
            cls._SUFIJO_CONTADOR_RE.sub("", actual_line).endswith(regla_formateada)
            for actual_line in reglas_actuales
        )

    @staticmethod
    def _revertir_escalar(puesto, previo, ahora, minusculas: bool = False) -> bool:
        if ahora is None:
            return True
        if minusculas:
            puesto, previo, ahora = str(puesto).lower(), str(previo).lower(), str(ahora).lower()
        return debe_revertir_escalar(puesto, previo, ahora)

    def _leer_actual_fresco_o_none(self, device: "Device") -> "GlobalConfig | None":
        try:
            return self._leer_actual_fresco(device)
        except Exception:
            return None

    def _leer_actual_fresco(self, device: "Device") -> "GlobalConfig | None":
        return self.reconciliar(device).get("actual")

    def _aplicar_acl_create(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        name = self.acl_create["name"]
        reglas_actuales = self._reglas_acl_actuales(actual, name)
        rule_lines = [
            formateada for r in self.acl_create["rules"]
            if not self._regla_ya_presente(formateada := device.driver.formatear_regla_acl(r), reglas_actuales)
        ]
        if not rule_lines:
            return self._noop_resultado("crear_o_extender_acl")
        resultado = device.driver.create_or_update_acl(name, rule_lines, device, device.password)
        return {**resultado, "accion": "crear_o_extender_acl"}

    def _aplicar_acl_rule_remove(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        estado = pre_state if pre_state is not None else self.reconciliar(device)
        actual = estado.get("actual")
        name = self.acl_rule_remove["name"]
        reglas_actuales = self._reglas_acl_actuales(actual, name)
        rule_lines = [
            formateada for r in self.acl_rule_remove["rules"]
            if self._regla_ya_presente(formateada := device.driver.formatear_regla_acl(r), reglas_actuales)
        ]
        if not rule_lines:
            return self._noop_resultado("sacar_reglas_acl")
        resultado = device.driver.remove_acl_rules(name, rule_lines, device, device.password)
        return {**resultado, "accion": "sacar_reglas_acl"}

    def _aplicar_acl_delete(self, device: "Device") -> dict:
        estado = self.reconciliar(device)
        actual = estado.get("actual")
        existe = actual is not None and actual.acls and any(a.get("name") == self.acl_delete for a in actual.acls)
        if not existe:
            return self._noop_resultado("borrar_acl")
        resultado = device.driver.delete_acl(self.acl_delete, device, device.password)
        return {**resultado, "accion": "borrar_acl"}

    _PREFIJO_REGLA_ACL_RE = re.compile(r"^\s*(?:rule\s+)?\d+\s+")
    _NUMERO_PREFIJO_REGLA_ACL_RE = re.compile(r"^\s*(?:rule\s+)?(\d+)\s+")

    @classmethod
    def _pelar_regla_acl(cls, raw_line: str) -> str:
        sin_contador = cls._SUFIJO_CONTADOR_RE.sub("", raw_line)
        return cls._PREFIJO_REGLA_ACL_RE.sub("", sin_contador).strip()

    @classmethod
    def _regla_con_secuencia_original(cls, bare: str, previas: list[str]) -> str:
        for raw in previas:
            sin_contador = cls._SUFIJO_CONTADOR_RE.sub("", raw)
            if sin_contador.rstrip().endswith(bare):
                m = cls._NUMERO_PREFIJO_REGLA_ACL_RE.match(sin_contador)
                if m:
                    return f"{m.group(1)} {bare}"
                break
        return bare

    def ejecutar_rollback(self, pre_state: dict, device: "Device") -> "tuple[bool, bool | None]":
        if not pre_state.get("existed"):
            return False, None
        anterior = pre_state.get("actual")
        if anterior is None:
            return False, None

        campos = self.mutation_fields
        if len(campos) != 1:
            return False, None
        campo = next(iter(campos))
        revertidos: "set[str] | None" = None
        try:
            if campo == "hostname":
                if not anterior.hostname or anterior.hostname == self.hostname:
                    return False, None
                ahora = self._leer_actual_fresco_o_none(device)
                if not self._revertir_escalar(
                    self.hostname, anterior.hostname, ahora.hostname if ahora else None, minusculas=True,
                ):
                    return False, None
                resultado = device.driver.set_hostname(anterior.hostname, device, device.password)
            elif campo == "snmp_config":
                cambios = {}
                ahora = self._leer_actual_fresco_o_none(device)
                version_puesta = self.snmp_config.get("version")
                if (
                    version_puesta is not None and anterior.snmp_version is not None
                    and self._revertir_escalar(
                        version_puesta, anterior.snmp_version, ahora.snmp_version if ahora else None,
                    )
                ):
                    cambios["version"] = anterior.snmp_version
                community_puesta = self.snmp_config.get("community")
                if (
                    community_puesta is not None and anterior.snmp_community is not None
                    and self._revertir_escalar(
                        community_puesta, anterior.snmp_community, ahora.snmp_community if ahora else None,
                    )
                ):
                    cambios["community"] = anterior.snmp_community
                revertidos = set(cambios)
                rcs = []
                if cambios:
                    rcs.append(device.driver.set_snmp(cambios, device, device.password).get("rc", 1))
                trap_host = self.snmp_config.get("trap_host")
                if trap_host is not None and trap_host not in (anterior.snmp_trap_hosts or []):
                    community_usada = self.snmp_config.get("community") or anterior.snmp_community
                    if community_usada:
                        rcs.append(
                            device.driver.remove_snmp_trap_host(
                                trap_host, device, device.password, community=community_usada,
                            ).get("rc", 1)
                        )
                if not rcs:
                    return False, None
                resultado = {"rc": 0 if all(rc == 0 for rc in rcs) else 1}
            elif campo == "snmp_trap_host_remove":
                resultado = device.driver.set_snmp(
                    {
                        "trap_host": self.snmp_trap_host_remove["host"],
                        "trap_host_community": self.snmp_trap_host_remove["community"],
                        "trap_version": anterior.snmp_version or "2c",
                    },
                    device, device.password,
                )
            elif campo == "route_add":
                destino = str(ipaddress.ip_network(self.route_add["destination"], strict=False))
                next_hop = self.route_add["next_hop"]
                ya_existia = any(
                    r.get("destination") == destino and r.get("next_hop") == next_hop
                    for r in (anterior.routes or [])
                )
                if ya_existia:
                    return False, None
                actual_ahora = self._leer_actual_fresco(device)
                esta_ahora = actual_ahora is not None and any(
                    r.get("destination") == destino and r.get("next_hop") == next_hop
                    for r in (actual_ahora.routes or [])
                )
                if not esta_ahora:
                    return False, None
                resultado = device.driver.remove_route(destino, next_hop, device, device.password)
            elif campo == "route_remove":
                destino = str(ipaddress.ip_network(self.route_remove["destination"], strict=False))
                next_hop = self.route_remove["next_hop"]
                existia = any(
                    r.get("destination") == destino and r.get("next_hop") == next_hop
                    for r in (anterior.routes or [])
                )
                if not existia:
                    return False, None
                resultado = device.driver.set_route(destino, next_hop, device, device.password)
            elif campo == "ntp_server_add":
                server = self.ntp_server_add["server"]
                if server in (anterior.ntp_servers or []):
                    return False, None
                actual_ahora = self._leer_actual_fresco(device)
                if actual_ahora is None or server not in (actual_ahora.ntp_servers or []):
                    return False, None
                resultado = device.driver.remove_ntp_server(server, device, device.password)
            elif campo == "ntp_server_remove":
                resultado = device.driver.add_ntp_server(
                    self.ntp_server_remove["server"], False, device, device.password,
                )
            elif campo == "dns_server_add":
                server = self.dns_server_add["server"]
                if server in (anterior.dns_servers or []):
                    return False, None
                actual_ahora = self._leer_actual_fresco(device)
                if actual_ahora is None or server not in (actual_ahora.dns_servers or []):
                    return False, None
                resultado = device.driver.remove_dns_server(server, device, device.password)
            elif campo == "dns_server_remove":
                resultado = device.driver.add_dns_server(self.dns_server_remove["server"], device, device.password)
            elif campo == "dns_domain_set":
                return False, None
            elif campo == "log_server_add":
                server = self.log_server_add["server"]
                if server in (anterior.log_servers or []):
                    return False, None
                actual_ahora = self._leer_actual_fresco(device)
                if actual_ahora is None or server not in (actual_ahora.log_servers or []):
                    return False, None
                resultado = device.driver.remove_log_server(server, device, device.password)
            elif campo == "log_server_remove":
                resultado = device.driver.add_log_server(
                    self.log_server_remove["server"], None, device, device.password,
                )
            elif campo == "acl_create":
                name = self.acl_create["name"]
                existia_antes = bool(anterior.acls) and any(a.get("name") == name for a in anterior.acls)
                actual_ahora = self._leer_actual_fresco(device)
                if not existia_antes:
                    existe_ahora = actual_ahora is not None and bool(actual_ahora.acls) and any(
                        a.get("name") == name for a in actual_ahora.acls
                    )
                    if not existe_ahora:
                        return False, None
                    resultado = device.driver.delete_acl(name, device, device.password)
                else:
                    previas = self._reglas_acl_actuales(anterior, name)
                    nuevas_relativas_a_anterior = [
                        formateada for r in self.acl_create["rules"]
                        if not self._regla_ya_presente(
                            formateada := device.driver.formatear_regla_acl(r), previas,
                        )
                    ]
                    if not nuevas_relativas_a_anterior:
                        return False, None
                    previas_ahora = self._reglas_acl_actuales(actual_ahora, name) if actual_ahora else []
                    agregadas = [
                        r for r in nuevas_relativas_a_anterior
                        if self._regla_ya_presente(r, previas_ahora)
                    ]
                    if not agregadas:
                        return False, None
                    resultado = device.driver.remove_acl_rules(name, agregadas, device, device.password)
            elif campo == "acl_rule_remove":
                name = self.acl_rule_remove["name"]
                previas = self._reglas_acl_actuales(anterior, name)
                sacadas_input = [
                    r for r in self.acl_rule_remove["rules"]
                    if self._regla_ya_presente(device.driver.formatear_regla_acl(r), previas)
                ]
                if not sacadas_input:
                    return False, None
                rule_lines = [
                    self._regla_con_secuencia_original(device.driver.formatear_regla_acl(r), previas)
                    for r in sacadas_input
                ]
                resultado = device.driver.create_or_update_acl(name, rule_lines, device, device.password)
            elif campo == "acl_delete":
                previas = self._reglas_acl_actuales(anterior, self.acl_delete)
                if not previas:
                    return False, None
                rule_lines = [self._pelar_regla_acl(r) for r in previas]
                resultado = device.driver.create_or_update_acl(self.acl_delete, rule_lines, device, device.password)
            else:
                return False, None
            exitoso = resultado.get("rc", 1) == 0
        except Exception:
            return True, False

        if not exitoso:
            return True, False

        try:
            actual_final = device.driver.get_global_config(device, device.password)
            if actual_final is None:
                verificado = False
            elif campo == "acl_create":
                if not existia_antes:
                    verificado = not (
                        actual_final.acls and any(a.get("name") == name for a in actual_final.acls)
                    )
                else:
                    reglas_ahora = self._reglas_acl_actuales(actual_final, name)
                    verificado = not any(
                        self._regla_ya_presente(r, reglas_ahora) for r in agregadas
                    )
            elif campo == "acl_rule_remove":
                reglas_ahora = self._reglas_acl_actuales(actual_final, name)
                verificado = all(
                    self._regla_ya_presente(device.driver.formatear_regla_acl(r), reglas_ahora)
                    for r in sacadas_input
                )
            elif campo == "acl_delete":
                existe_ahora = bool(actual_final.acls) and any(
                    a.get("name") == self.acl_delete for a in actual_final.acls
                )
                reglas_ahora = self._reglas_acl_actuales(actual_final, self.acl_delete) if existe_ahora else []
                verificado = existe_ahora and all(
                    self._regla_ya_presente(r, reglas_ahora) for r in rule_lines
                )
            else:
                verificado = self._verificar_rollback(campo, anterior, actual_final, revertidos)
        except Exception:
            verificado = False
        return True, verificado

    def _verificar_rollback(self, campo: str, anterior, actual_final, revertidos: "set[str] | None" = None) -> bool:
        if actual_final is None:
            return False
        if campo == "hostname":
            return actual_final.hostname == anterior.hostname
        if campo == "snmp_config":
            trap_host = self.snmp_config.get("trap_host")
            trap_ok = (
                trap_host is None
                or trap_host in (anterior.snmp_trap_hosts or [])
                or trap_host not in (actual_final.snmp_trap_hosts or [])
            )
            def ok(clave: str, actual, previo) -> bool:
                return (revertidos is not None and clave not in revertidos) or actual == previo

            return (
                ok("version", actual_final.snmp_version, anterior.snmp_version)
                and ok("community", actual_final.snmp_community, anterior.snmp_community)
                and trap_ok
            )
        if campo == "snmp_trap_host_remove":
            return True
        if campo in ("route_add", "route_remove"):
            return (actual_final.routes or []) == (anterior.routes or [])
        if campo == "ntp_server_add":
            return self.ntp_server_add["server"] not in (actual_final.ntp_servers or [])
        if campo == "ntp_server_remove":
            return self.ntp_server_remove["server"] in (actual_final.ntp_servers or [])
        if campo == "dns_server_add":
            return self.dns_server_add["server"] not in (actual_final.dns_servers or [])
        if campo == "dns_server_remove":
            return self.dns_server_remove["server"] in (actual_final.dns_servers or [])
        if campo == "log_server_add":
            return self.log_server_add["server"] not in (actual_final.log_servers or [])
        if campo == "log_server_remove":
            return self.log_server_remove["server"] in (actual_final.log_servers or [])
        return False

    def repositorio(self) -> str:
        return "global_config"

    def resumen_intento(self) -> str:
        campos = self.mutation_fields
        if not campos:
            return "Global config: no changes"
        return "; ".join(self._describir_campo_mutacion(c) for c in sorted(campos))

    def _describir_campo_mutacion(self, campo: str) -> str:
        valor = getattr(self, campo)
        if campo == "hostname":
            return f"Set hostname to '{valor}'"
        if campo == "snmp_config":
            detalles = ", ".join(f"{k}={v}" for k, v in valor.items() if v is not None)
            return f"Update SNMP ({detalles})" if detalles else "Update SNMP"
        if campo == "snmp_trap_host_remove":
            return f"Remove SNMP trap host {valor.get('host')}"
        if campo == "route_add":
            return f"Add route {valor.get('destination')} -> {valor.get('next_hop')}"
        if campo == "route_remove":
            return f"Remove route {valor.get('destination')} -> {valor.get('next_hop')}"
        if campo == "ntp_server_add":
            return f"Add NTP server {valor.get('server')}"
        if campo == "ntp_server_remove":
            return f"Remove NTP server {valor.get('server')}"
        if campo == "dns_server_add":
            return f"Add DNS server {valor.get('server')}"
        if campo == "dns_server_remove":
            return f"Remove DNS server {valor.get('server')}"
        if campo == "dns_domain_set":
            return f"Set DNS domain-name to '{valor}'"
        if campo == "log_server_add":
            nivel = f" (level {valor.get('level')})" if valor.get("level") else ""
            return f"Add log server {valor.get('server')}{nivel}"
        if campo == "log_server_remove":
            return f"Remove log server {valor.get('server')}"
        if campo == "acl_create":
            n = len(valor.get("rules") or [])
            return f"Create/update ACL '{valor.get('name')}' ({n} rule{'s' if n != 1 else ''})"
        if campo == "acl_rule_remove":
            n = len(valor.get("rules") or [])
            return f"Remove {n} rule{'s' if n != 1 else ''} from ACL '{valor.get('name')}'"
        if campo == "acl_delete":
            return f"Delete ACL '{valor}'"
        return f"{campo}: {valor!r}"

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "hostname": self.hostname,
            "running_config": self.running_config,
            "device_version": self.device_version,
            "snmp_enabled": self.snmp_enabled,
            "snmp_version": self.snmp_version,
            "snmp_community": self.snmp_community,
            "snmp_permission": self.snmp_permission,
            "snmp_trap_hosts": self.snmp_trap_hosts,
            "ntp_servers": self.ntp_servers,
            "dns_servers": self.dns_servers,
            "log_servers": self.log_servers,
            "log_level": self.log_level,
            "routes": self.routes,
            "acls": self.acls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
