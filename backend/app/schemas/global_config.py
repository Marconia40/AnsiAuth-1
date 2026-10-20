from __future__ import annotations

import ipaddress
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _validar_ip_unica(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    try:
        ipaddress.ip_address(v)
    except ValueError:
        raise ValueError(f"must be a single valid IP address (e.g. '192.0.2.5'), got {v!r}") from None
    return v


def _validar_red_cidr(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if "/" not in v:
        raise ValueError(f"must include a prefix length (e.g. '192.168.99.0/24'), got {v!r}") from None
    try:
        ipaddress.ip_network(v, strict=False)
    except ValueError:
        raise ValueError(f"must be a valid CIDR network (e.g. '192.168.99.0/24'), got {v!r}") from None
    return v


class GlobalConfigHostnameUpdateRequest(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=63, description="Nuevo hostname del device.")


class GlobalConfigSnmpUpdateRequest(BaseModel):
    version: Optional[str] = Field(None, description="Versión SNMP a habilitar (ej. 'v2c'). Solo tiene efecto en VRP.")
    community: Optional[str] = Field(None, min_length=1, description="Community SNMP a configurar (siempre solo lectura).")
    trap_source: Optional[str] = Field(None, min_length=1, description="Interfaz de administración usada como origen de los traps.")
    trap_host: Optional[str] = Field(None, min_length=1, description="IP destino de los traps SNMP.")
    trap_version: Optional[str] = Field(None, min_length=1, description="Versión SNMP del trap-host (ej. '2c'). Requerido junto con trap_host.")

    @field_validator("trap_host")
    @classmethod
    def _validar_trap_host(cls, v: Optional[str]) -> Optional[str]:
        return _validar_ip_unica(v)

    @model_validator(mode="after")
    def _validate(self) -> "GlobalConfigSnmpUpdateRequest":
        if (self.trap_host is None) != (self.trap_version is None):
            raise ValueError("'trap_host' and 'trap_version' must be provided together")
        if not any((self.version, self.community, self.trap_source, self.trap_host)):
            raise ValueError("at least one of version, community, trap_source, trap_host+trap_version must be provided")
        return self


class GlobalConfigSnmpTrapHostRemoveRequest(BaseModel):
    host: str = Field(..., min_length=1, description="IP del trap host a sacar.")
    community: str = Field(
        ..., min_length=1,
        description="Community usada al agregar este trap host. Requerida en ambos vendors.",
    )

    @field_validator("host")
    @classmethod
    def _validar_host(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigLogServerAddRequest(BaseModel):
    server: str = Field(..., min_length=1, description="IP del servidor de Syslog a agregar.")
    level: Optional[str] = Field(None, min_length=1, description="Nivel de severidad a configurar junto con este server.")

    @field_validator("server")
    @classmethod
    def _validar_server(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigLogServerRemoveRequest(BaseModel):
    server: str = Field(..., min_length=1, description="IP del servidor de Syslog a sacar.")

    @field_validator("server")
    @classmethod
    def _validar_server(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigRouteAddRequest(BaseModel):
    destination: str = Field(..., min_length=1, description="Red destino en notación CIDR (ej. '192.168.99.0/24').")
    next_hop: str = Field(..., min_length=1, description="IP del next-hop.")

    @field_validator("destination")
    @classmethod
    def _validar_destination(cls, v: str) -> str:
        return _validar_red_cidr(v)

    @field_validator("next_hop")
    @classmethod
    def _validar_next_hop(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigNtpAddRequest(BaseModel):
    server: str = Field(..., min_length=1, description="IP del servidor NTP a agregar.")
    prefer: Optional[bool] = Field(None, description="Marca este server como preferido (Cisco). Sin efecto confirmado en Huawei.")

    @field_validator("server")
    @classmethod
    def _validar_server(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigNtpRemoveRequest(BaseModel):
    server: str = Field(..., min_length=1, description="IP del servidor NTP a sacar.")

    @field_validator("server")
    @classmethod
    def _validar_server(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigDnsRequest(BaseModel):
    server: Optional[str] = Field(None, min_length=1, description="IP de un DNS server a agregar.")
    domain_name: Optional[str] = Field(None, min_length=1, description="Domain-name a configurar en el device.")

    @field_validator("server")
    @classmethod
    def _validar_server(cls, v: Optional[str]) -> Optional[str]:
        return _validar_ip_unica(v)

    @model_validator(mode="after")
    def _exactly_one(self) -> "GlobalConfigDnsRequest":
        if (self.server is None) == (self.domain_name is None):
            raise ValueError("exactly one of 'server' or 'domain_name' must be provided")
        return self


class GlobalConfigDnsRemoveRequest(BaseModel):
    server: str = Field(..., min_length=1, description="IP del DNS server a sacar.")

    @field_validator("server")
    @classmethod
    def _validar_server(cls, v: str) -> str:
        return _validar_ip_unica(v)


class GlobalConfigVersionRead(BaseModel):
    software_version: Optional[str] = Field(None, description="Versión de software extraída (best-effort).")
    model: Optional[str] = Field(None, description="Modelo de hardware extraído (best-effort).")
    uptime: Optional[str] = Field(None, description="Uptime tal cual lo reporta el device (best-effort).")


class GlobalConfigRunningConfigRead(BaseModel):
    running_config: Optional[list[str]] = Field(
        None,
        description=(
            "Dump completo de 'show running-config'/'display current-configuration' "
            "como lista de líneas (no 1 solo string), o null si no se pudo leer. "
            "Ya viene sin las líneas de metadata iniciales (ver "
            "GlobalConfig.running_config)."
        ),
    )


class GlobalConfigSnmpInfo(BaseModel):
    enabled: Optional[bool] = Field(
        None, description="True si SNMP está habilitado en el device, False si no, null si no se pudo determinar.",
    )
    version: Optional[str] = Field(
        None,
        description=(
            "Versión SNMP -- en VRP viene de 'snmp-agent sys-info version' (puede ser "
            "más de 1, ej. 'v2c v3'); en IOS clásico no hay ajuste de versión "
            "independiente, se toma de la línea de trap-host si hay una configurada. "
            "Null si no se pudo determinar ninguna."
        ),
    )
    community: Optional[str] = Field(
        None,
        description=(
            "Community SNMP configurada, o null (incluye el caso SNMP deshabilitado). "
            "En Huawei siempre da null aunque haya una configurada -- VRP la guarda cifrada, "
            "no se puede revertir del lado del parser."
        ),
    )
    permission: Optional[str] = Field(None, description="Permiso de la community ('RO'/'RW'), o null.")
    trap_hosts: Optional[list[str]] = Field(
        None,
        description=(
            "En Cisco, IPs destino reales de los traps SNMP ('snmp-server host', puede haber "
            "más de 1 línea). En Huawei no hay trap-host leíble ('snmp-agent target-host' no "
            "tiene lectura implementada) -- se toman en cambio TODOS los hosts permitidos por "
            "la ACL que 'snmp-agent acl {nombre}' ata al agente SNMP (misma ACL que aparece "
            "en 'acls'). Null si no hay ninguno configurado o no se pudo resolver."
        ),
    )


class GlobalConfigNtpInfo(BaseModel):
    servers: Optional[list[str]] = Field(
        None, description="Servidores NTP configurados (todos, no solo el primero), o null.",
    )


class GlobalConfigDnsInfo(BaseModel):
    servers: Optional[list[str]] = Field(
        None, description="Servidores DNS configurados (todos, no solo el primero), o null.",
    )


class GlobalConfigLoggingInfo(BaseModel):
    servers: Optional[list[str]] = Field(
        None, description="Servidores de Syslog configurados (todos, no solo el primero), o null.",
    )
    level: Optional[str] = Field(None, description="Nivel de log configurado, o null.")


class GlobalConfigAclInfo(BaseModel):
    name: str = Field(..., description="Nombre o número de la ACL.")
    type: Optional[str] = Field(
        None,
        description=(
            "Tipo de ACL tal cual lo reporta el device -- 'standard'/'extended' en Cisco, "
            "'basic'/'advanced'/'ethernet frame'/'user' en Huawei."
        ),
    )
    rules: list[str] = Field(
        default_factory=list, description="Reglas de la ACL, 1 línea cruda por regla (formato vendor-específico).",
    )


class GlobalConfigAclRuleEndpoint(BaseModel):
    any: Optional[bool] = Field(None, description="True para 'any' (cualquier origen/destino).")
    host: Optional[str] = Field(None, min_length=1, description="1 solo host (ej. '192.0.2.5').")
    network: Optional[str] = Field(None, min_length=1, description="Red en notación CIDR (ej. '192.0.2.0/24').")

    @model_validator(mode="after")
    def _exactly_one(self) -> "GlobalConfigAclRuleEndpoint":
        provided = [v for v in (self.any, self.host, self.network) if v not in (None, False)]
        if len(provided) != 1:
            raise ValueError("exactly one of 'any', 'host', 'network' must be provided")
        if self.host is not None:
            try:
                ipaddress.ip_address(self.host)
            except ValueError:
                raise ValueError(
                    "'host' must be a single IP address with no prefix "
                    "(e.g. '192.0.2.5') -- use 'network' for a CIDR range"
                )
        if self.network is not None:
            if "/" not in self.network:
                raise ValueError(
                    "'network' must include a prefix length (e.g. '192.0.2.0/24') "
                    "-- use 'host' for a single IP"
                )
            try:
                ipaddress.ip_network(self.network, strict=False)
            except ValueError:
                raise ValueError(
                    "'network' must be a valid CIDR range (e.g. '192.0.2.0/24')"
                )
        return self


class GlobalConfigAclRulePort(BaseModel):
    operator: Literal["eq", "range"] = Field(..., description="'eq' (puerto/servicio único) o 'range' (rango).")
    value: str = Field(..., min_length=1, description="Puerto/servicio (ej. 'bootps', '443') o inicio del rango.")
    value2: Optional[str] = Field(None, min_length=1, description="Fin del rango. Requerido solo si operator='range'.")

    @model_validator(mode="after")
    def _range_needs_value2(self) -> "GlobalConfigAclRulePort":
        if self.operator == "range" and not self.value2:
            raise ValueError("'value2' is required when operator='range'")
        if self.operator == "eq" and self.value2:
            raise ValueError("'value2' is only valid when operator='range'")
        return self


class GlobalConfigAclRule(BaseModel):
    action: Literal["permit", "deny"]
    protocol: str = Field(..., min_length=1)
    source: GlobalConfigAclRuleEndpoint
    destination: GlobalConfigAclRuleEndpoint
    port: Optional[GlobalConfigAclRulePort] = Field(
        None, description="Puerto/rango opcional (típicamente solo tiene sentido con tcp/udp).",
    )


class GlobalConfigAclCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nombre de la ACL a crear o extender.")
    rules: list[GlobalConfigAclRule] = Field(..., min_length=1, description="Reglas a agregar (al menos 1).")


class GlobalConfigAclRuleRemoveRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nombre de la ACL de la que sacar reglas.")
    rules: list[GlobalConfigAclRule] = Field(..., min_length=1, description="Reglas a sacar (al menos 1).")


class GlobalConfigAclDeleteRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nombre de la ACL a borrar completa.")


class GlobalConfigRead(BaseModel):
    hostname: Optional[str] = Field(None, description="Hostname configurado en el device, o null.")
    snmp: GlobalConfigSnmpInfo = Field(default_factory=GlobalConfigSnmpInfo)
    ntp: GlobalConfigNtpInfo = Field(default_factory=GlobalConfigNtpInfo)
    dns: GlobalConfigDnsInfo = Field(default_factory=GlobalConfigDnsInfo)
    logging: GlobalConfigLoggingInfo = Field(default_factory=GlobalConfigLoggingInfo)
    routes: Optional[list[dict]] = Field(
        None,
        description=(
            "Tabla de ruteo (destino/next_hop/interfaz), o null si no se pudo leer. "
            "next_hop/interfaz son individualmente null según el tipo de ruta -- una "
            "conectada no tiene next_hop (por definición, sale directo por la interfaz), "
            "y una ruta estática vía next-hop puede no traer interfaz si el device no la "
            "resuelve en el 'show ip route'/'display ip routing-table' (confirmado en vivo, "
            "no es un gap del parser). Incluye también rutas estáticas configuradas cuyo "
            "next_hop no es alcanzable (no aparecen en la tabla activa, pero SÍ en el "
            "running-config -- se leen de ahí también) para que se puedan ver y borrar "
            "desde la interfaz aunque no estén activas."
        ),
    )
    acls: Optional[list[GlobalConfigAclInfo]] = Field(
        None, description="ACLs configuradas en el device, con sus reglas, o null.",
    )
