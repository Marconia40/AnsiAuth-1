from __future__ import annotations

import ipaddress
import re
from abc import ABC, abstractmethod

from app.models.global_config import GlobalConfig
from app.services.parsers._common import strip_ansi


class GlobalConfigParser(ABC):
    @classmethod
    @abstractmethod
    def parse(cls, **raw_outputs: str) -> GlobalConfig:
        ...


_IOS_HOSTNAME_LINE = re.compile(r"^hostname\s+(\S+)\s*$", re.IGNORECASE)
_IOS_SNMP_COMMUNITY_LINE = re.compile(
    r"^snmp-server community\s+(\S+)\s+(RO|RW)\b", re.IGNORECASE,
)
_IOS_ROUTE_CONNECTED_RE = re.compile(
    r"^[A-Z*]{1,3}\s+(\S+/\d+)\s+is directly connected,\s+(\S+)", re.IGNORECASE,
)
_IOS_ROUTE_VIA_RE = re.compile(
    r"^[A-Z*]{1,3}\s+(\S+/\d+)\s+\[\d+/\d+\]\s+via\s+(\S+?),?(?:\s|$)", re.IGNORECASE,
)
_IOS_STATIC_ROUTE_RE = re.compile(
    r"^ip route\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_IOS_NTP_SERVER_RE = re.compile(r"^ntp server\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_IOS_DNS_SERVER_RE = re.compile(r"^ip name-server\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_IOS_LOG_HOST_RE = re.compile(r"^logging host\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_IOS_LOG_LEVEL_RE = re.compile(r"^logging trap\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_IOS_SNMP_TRAP_HOST_VERSION_RE = re.compile(
    r"^snmp-server host\s+(\S+)\s+version\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_IOS_DEFAULT_GATEWAY_RE = re.compile(r"^Default gateway is\s+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE | re.MULTILINE)


class CiscoGlobalConfigParser(GlobalConfigParser):
    @classmethod
    def parse(
        cls, *, version_output: str = "", hostname_output: str = "",
        community_output: str = "", route_output: str = "",
        running_config_output: str = "", snmp_enabled: bool | None = None,
    ) -> GlobalConfig:
        hostname = None
        for raw in hostname_output.splitlines():
            m = _IOS_HOSTNAME_LINE.match(strip_ansi(raw).rstrip())
            if m:
                hostname = m.group(1)
                break

        snmp_community = snmp_permission = None
        for raw in community_output.splitlines():
            m = _IOS_SNMP_COMMUNITY_LINE.match(strip_ansi(raw).rstrip())
            if m:
                snmp_community, snmp_permission = m.group(1), m.group(2).upper()
                break

        rc = strip_ansi(running_config_output)

        routes: list[dict] = []
        routes_por_clave: dict[tuple[str, str | None], dict] = {}
        for raw in route_output.splitlines():
            line = strip_ansi(raw).rstrip()
            m = _IOS_ROUTE_CONNECTED_RE.match(line)
            if m:
                ruta = {"destination": m.group(1), "next_hop": None, "interface": m.group(2)}
                routes.append(ruta)
                routes_por_clave[(ruta["destination"], ruta["next_hop"])] = ruta
                continue
            m = _IOS_ROUTE_VIA_RE.match(line)
            if m:
                ruta = {"destination": m.group(1), "next_hop": m.group(2), "interface": None}
                routes.append(ruta)
                routes_por_clave[(ruta["destination"], ruta["next_hop"])] = ruta
        for dest, mask, next_hop in _IOS_STATIC_ROUTE_RE.findall(rc):
            try:
                destino = str(ipaddress.ip_network(f"{dest}/{mask}", strict=False))
            except ValueError:
                continue
            clave = (destino, next_hop)
            if clave not in routes_por_clave:
                ruta = {"destination": destino, "next_hop": next_hop, "interface": None}
                routes.append(ruta)
                routes_por_clave[clave] = ruta
        m_gateway = _IOS_DEFAULT_GATEWAY_RE.search(strip_ansi(route_output))
        if m_gateway:
            routes.append({
                "destination": None, "next_hop": m_gateway.group(1), "interface": None,
                "tipo": "default-gateway",
            })

        version_text = strip_ansi(version_output).strip() or None
        ntp_servers = _IOS_NTP_SERVER_RE.findall(rc)
        dns_servers = [ip for linea in _IOS_DNS_SERVER_RE.findall(rc) for ip in linea.split()]
        log_servers = _IOS_LOG_HOST_RE.findall(rc)
        m_log_level = _IOS_LOG_LEVEL_RE.search(rc)
        snmp_traps = _IOS_SNMP_TRAP_HOST_VERSION_RE.findall(rc)

        return GlobalConfig(
            hostname=hostname,
            device_version=version_text,
            snmp_enabled=snmp_enabled,
            snmp_community=snmp_community,
            snmp_permission=snmp_permission,
            snmp_version=snmp_traps[0][1] if snmp_traps else None,
            snmp_trap_hosts=[host for host, _version in snmp_traps] or None,
            ntp_servers=ntp_servers or None,
            dns_servers=dns_servers or None,
            log_servers=log_servers or None,
            log_level=m_log_level.group(1) if m_log_level else None,
            routes=routes if (route_output.strip() or running_config_output.strip()) else None,
        )


_VRP_HOSTNAME_LINE = re.compile(r"^sysname\s+(\S+)\s*$", re.IGNORECASE)
_VRP_ROUTE_LINE = re.compile(
    r"^\s*(\S+/\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+\S*\s+(\S+)\s+(\S+)\s*$",
)
_VRP_STATIC_ROUTE_RE = re.compile(
    r"^ip route-static\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_VRP_NTP_SERVER_RE = re.compile(r"^ntp(?:-service)?\s+unicast-server\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VRP_DNS_SERVER_RE = re.compile(r"^dns server\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VRP_LOG_HOST_RE = re.compile(r"^info-center loghost\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VRP_LOG_LEVEL_RE = re.compile(
    r"^info-center source default channel\s+\d+\s+log level\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_VRP_SNMP_VERSION_RE = re.compile(r"^snmp-agent sys-info version\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_VRP_SNMP_PERMISSION_RE = re.compile(r"^snmp-agent community\s+(read|write)\b", re.IGNORECASE | re.MULTILINE)
_VRP_SNMP_ACL_RE = re.compile(r"^snmp-agent acl\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VRP_ACL_RULE_SOURCE_IP_RE = re.compile(r"^rule\s+\d+\s+permit\s+source\s+(\S+)", re.IGNORECASE)


class HuaweiGlobalConfigParser(GlobalConfigParser):
    @classmethod
    def parse(
        cls, *, version_output: str = "", hostname_output: str = "",
        route_output: str = "", running_config_output: str = "", snmp_enabled: bool | None = None,
        acls: list[dict] | None = None,
    ) -> GlobalConfig:
        hostname = None
        for raw in hostname_output.splitlines():
            m = _VRP_HOSTNAME_LINE.match(strip_ansi(raw).rstrip())
            if m:
                hostname = m.group(1)
                break

        rc = strip_ansi(running_config_output)

        routes: list[dict] = []
        routes_por_clave: dict[tuple[str, str | None], dict] = {}
        for raw in route_output.splitlines():
            line = strip_ansi(raw).rstrip()
            m = _VRP_ROUTE_LINE.match(line)
            if m and "/" in m.group(1):
                ruta = {
                    "destination": m.group(1), "next_hop": m.group(5), "interface": m.group(6),
                }
                routes.append(ruta)
                routes_por_clave[(ruta["destination"], ruta["next_hop"])] = ruta
        for dest, mask, next_hop in _VRP_STATIC_ROUTE_RE.findall(rc):
            try:
                destino = str(ipaddress.ip_network(f"{dest}/{mask}", strict=False))
            except ValueError:
                continue
            clave = (destino, next_hop)
            if clave not in routes_por_clave:
                ruta = {"destination": destino, "next_hop": next_hop, "interface": None}
                routes.append(ruta)
                routes_por_clave[clave] = ruta

        version_text = strip_ansi(version_output).strip() or None
        ntp_servers = _VRP_NTP_SERVER_RE.findall(rc)
        dns_servers = _VRP_DNS_SERVER_RE.findall(rc)
        log_servers = _VRP_LOG_HOST_RE.findall(rc)
        m_log_level = _VRP_LOG_LEVEL_RE.search(rc)
        m_snmp_version = _VRP_SNMP_VERSION_RE.search(rc)
        m_snmp_permission = _VRP_SNMP_PERMISSION_RE.search(rc)
        snmp_permission = {"read": "RO", "write": "RW"}.get(m_snmp_permission.group(1).lower()) if m_snmp_permission else None

        snmp_trap_hosts = None
        acl_name = None
        m_snmp_acl = _VRP_SNMP_ACL_RE.search(rc)
        if m_snmp_acl:
            acl_name = m_snmp_acl.group(1)
            if acls:
                acl = next((a for a in acls if a.get("name") == acl_name), None)
                if acl is not None:
                    hosts = [
                        m_ip.group(1) for regla in acl.get("rules", [])
                        if (m_ip := _VRP_ACL_RULE_SOURCE_IP_RE.match(regla))
                    ]
                    snmp_trap_hosts = hosts or None

        return GlobalConfig(
            hostname=hostname,
            device_version=version_text,
            snmp_enabled=snmp_enabled,
            snmp_community=None,
            snmp_permission=snmp_permission,
            snmp_version=m_snmp_version.group(1) if m_snmp_version else None,
            snmp_trap_hosts=snmp_trap_hosts,
            snmp_acl_name=acl_name,
            ntp_servers=ntp_servers or None,
            dns_servers=dns_servers or None,
            log_servers=log_servers or None,
            log_level=m_log_level.group(1) if m_log_level else None,
            routes=routes if (route_output.strip() or running_config_output.strip()) else None,
        )
