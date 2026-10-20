from __future__ import annotations

import ipaddress
import re
from abc import ABC, abstractmethod
from collections import Counter

from app.models.svi import SVI, DhcpRelayLayout
from app.services.parsers._common import strip_ansi


def _direccion_y_mascara_a_cidr(addr: str, mascara: str) -> str:
    try:
        return str(ipaddress.ip_interface(f"{addr}/{mascara}"))
    except ValueError:
        return f"{addr}/{mascara}"


def _normalizar_ipv6(cidr: str) -> str:
    try:
        return str(ipaddress.ip_interface(cidr))
    except ValueError:
        return cidr


def bloques_interface_vlan(running_config: str) -> str:
    lineas: list[str] = []
    dentro = False
    for raw in running_config.splitlines():
        linea = strip_ansi(raw).rstrip()
        if linea and not linea[0].isspace():
            dentro = bool(_IOS_IFACE_HEADER.match(linea))
        if dentro:
            lineas.append(linea)
    return "\n".join(lineas)


class SVIParser(ABC):
    @classmethod
    @abstractmethod
    def parse_svis(cls, config_output: str, brief_output: str, **kwargs) -> list[SVI]:
        ...


_IOS_IFACE_HEADER = re.compile(r"^interface\s+Vlan(\d+)\s*$", re.IGNORECASE)
_IOS_DESCRIPTION = re.compile(r"^\s*description\s+(.+?)\s*$")
_IOS_SHUTDOWN = re.compile(r"^\s*shutdown\s*$")
_IOS_IPV4_SECONDARY = re.compile(r"^\s*ip address\s+(\S+)\s+(\S+)\s+secondary\s*$", re.IGNORECASE)
_IOS_IPV4 = re.compile(r"^\s*ip address\s+(\S+)\s+(\S+)\s*$")
_IOS_IPV6 = re.compile(r"^\s*ipv6 address\s+(\S+)\s*$")
_IOS_ACL = re.compile(r"^\s*ip access-group\s+(\S+)\s+(in|out)\s*$", re.IGNORECASE)
_IOS_HELPER = re.compile(r"^\s*ip helper-address\s+(\S+)\s*$")

_IOS_BRIEF_LINE = re.compile(
    r"^Vlan(\d+)\s+\S+\s+\S+\s+\S+\s+(.+?)\s+(up|down)\s*$",
    re.IGNORECASE,
)


class CiscoSVIParser(SVIParser):
    @classmethod
    def parse_svis(cls, running_config_output: str, brief_output: str, **kwargs) -> list[SVI]:
        estado_por_vlan: dict[int, tuple[bool, bool]] = {}
        for raw in brief_output.splitlines():
            line = strip_ansi(raw).rstrip()
            m = _IOS_BRIEF_LINE.match(line)
            if not m:
                continue
            vlan_id, status_text, protocol = int(m.group(1)), m.group(2), m.group(3)
            admin_up = "administratively down" not in status_text.lower()
            operational_up = protocol.lower() == "up"
            estado_por_vlan[vlan_id] = (admin_up, operational_up)

        interfaces: list[SVI] = []
        actual: SVI | None = None
        helpers: list[str] = []
        secundarias: list[str] = []

        def _cerrar_actual() -> None:
            if actual is not None:
                actual.dhcp_relay_servers = helpers[:] if helpers else None
                actual.ipv4_address_secondary = secundarias[:] if secundarias else None
                interfaces.append(actual)

        for raw in running_config_output.splitlines():
            line = strip_ansi(raw).rstrip()
            header = _IOS_IFACE_HEADER.match(line)
            if header:
                _cerrar_actual()
                vlan_id = int(header.group(1))
                admin_up, operational_up = estado_por_vlan.get(vlan_id, (None, None))
                actual = SVI(vlan_id=vlan_id, admin_up=admin_up, operational_up=operational_up)
                helpers = []
                secundarias = []
                continue
            if actual is None:
                continue
            if _IOS_SHUTDOWN.match(line):
                actual.admin_up = False
                continue
            m = _IOS_DESCRIPTION.match(line)
            if m:
                actual.description = m.group(1)
                continue
            m = _IOS_IPV4_SECONDARY.match(line)
            if m:
                secundarias.append(_direccion_y_mascara_a_cidr(m.group(1), m.group(2)))
                continue
            m = _IOS_IPV4.match(line)
            if m:
                actual.ipv4_address = _direccion_y_mascara_a_cidr(m.group(1), m.group(2))
                continue
            m = _IOS_IPV6.match(line)
            if m:
                actual.ipv6_address = m.group(1)
                continue
            m = _IOS_ACL.match(line)
            if m:
                if m.group(2).lower() == "in":
                    actual.acl_in = m.group(1)
                else:
                    actual.acl_out = m.group(1)
                continue
            m = _IOS_HELPER.match(line)
            if m:
                helpers.append(m.group(1))
                continue

        _cerrar_actual()
        return interfaces


def parse_ios_svis(running_config_output: str, brief_output: str) -> list[SVI]:
    return CiscoSVIParser.parse_svis(running_config_output, brief_output)


_VRP_IFACE_HEADER = re.compile(r"^interface\s+Vlanif(\d+)\s*$", re.IGNORECASE)
_VRP_DESCRIPTION = re.compile(r"^\s*description\s+(.+?)\s*$")
_VRP_SHUTDOWN = re.compile(r"^\s*shutdown\s*$")
_VRP_IPV4_SECONDARY = re.compile(r"^\s*ip address\s+(\S+)\s+(\S+)\s+sub\s*$", re.IGNORECASE)
_VRP_IPV4 = re.compile(r"^\s*ip address\s+(\S+)\s+(\S+)\s*$")
_VRP_IPV6 = re.compile(r"^\s*ipv6 address\s+(\S+)\s*$")
_VRP_ACL_LINE = re.compile(
    r"^\s*traffic-filter\s+"
    r"(?:(?P<dir1>inbound|outbound)\s+)?"
    r"acl\s+(?:name\s+)?(?P<target>\S+)"
    r"(?:\s+(?P<dir2>inbound|outbound))?"
    r"\s*$",
    re.IGNORECASE,
)
_VRP_HELPER = re.compile(r"^\s*dhcp relay server-ip\s+(\S+)\s*$", re.IGNORECASE)
_VRP_BINDING = re.compile(r"^\s*dhcp relay binding server group\s+(\S+)\s*$", re.IGNORECASE)

_VRP_BRIEF_LINE = re.compile(
    r"^Vlanif(\d+)\s+\S+\s+(up|down|\*down)\s+(up|down)\s*", re.IGNORECASE,
)

_VRP_GROUP_HEADER = re.compile(r"^dhcp relay server group\s+(\S+)\s*$", re.IGNORECASE)
_VRP_GROUP_SERVER = re.compile(r"^\s*server\s+(\S+)\s+(\d+)\s*$", re.IGNORECASE)


class HuaweiSVIParser(SVIParser):
    @classmethod
    def parse_dhcp_relay_groups(cls, dhcp_config_output: str) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        current: str | None = None
        for raw in dhcp_config_output.splitlines():
            line = strip_ansi(raw).rstrip()
            header = _VRP_GROUP_HEADER.match(line)
            if header:
                current = header.group(1)
                groups.setdefault(current, [])
                continue
            if current is None:
                continue
            m = _VRP_GROUP_SERVER.match(line)
            if m:
                groups[current].append(m.group(1))
                continue
            if line.strip() == "#":
                current = None
        return groups

    @classmethod
    def parse_dhcp_relay_group_entries(cls, dhcp_config_output: str) -> dict[str, dict[str, int]]:
        groups: dict[str, dict[str, int]] = {}
        current: str | None = None
        for raw in dhcp_config_output.splitlines():
            line = strip_ansi(raw).rstrip()
            header = _VRP_GROUP_HEADER.match(line)
            if header:
                current = header.group(1)
                groups.setdefault(current, {})
                continue
            if current is None:
                continue
            m = _VRP_GROUP_SERVER.match(line)
            if m:
                groups[current][m.group(1)] = int(m.group(2))
                continue
            if line.strip() == "#":
                current = None
        return groups

    @classmethod
    def parse_svis(
        cls, config_output: str, brief_output: str,
        dhcp_groups: "dict[str, list[str]] | None" = None,
        dhcp_group_entries: "dict[str, dict[str, int]] | None" = None, **kwargs,
    ) -> list[SVI]:
        dhcp_groups = dhcp_groups or {}
        estado_por_vlan: dict[int, tuple[bool, bool]] = {}
        for raw in brief_output.splitlines():
            line = strip_ansi(raw).rstrip()
            m = _VRP_BRIEF_LINE.match(line)
            if not m:
                continue
            vlan_id, physical, protocol = int(m.group(1)), m.group(2), m.group(3)
            admin_up = not physical.lower().startswith("*")
            operational_up = protocol.lower() == "up"
            estado_por_vlan[vlan_id] = (admin_up, operational_up)

        interfaces: list[SVI] = []
        actual: SVI | None = None
        helpers: list[str] = []
        secundarias: list[str] = []
        binding_group: str | None = None
        grupo_por_vlan: dict[int, str] = {}
        directas: set[int] = set()

        def _cerrar_actual() -> None:
            if actual is not None:
                if binding_group is not None:
                    actual.dhcp_relay_servers = dhcp_groups.get(binding_group) or None
                    grupo_por_vlan[actual.vlan_id] = binding_group
                else:
                    actual.dhcp_relay_servers = helpers[:] if helpers else None
                    if helpers:
                        directas.add(actual.vlan_id)
                actual.ipv4_address_secondary = secundarias[:] if secundarias else None
                interfaces.append(actual)

        for raw in config_output.splitlines():
            line = strip_ansi(raw).rstrip()
            header = _VRP_IFACE_HEADER.match(line)
            if header:
                _cerrar_actual()
                vlan_id = int(header.group(1))
                admin_up, operational_up = estado_por_vlan.get(vlan_id, (None, None))
                actual = SVI(vlan_id=vlan_id, admin_up=admin_up, operational_up=operational_up)
                helpers = []
                secundarias = []
                binding_group = None
                continue
            if actual is None:
                continue
            if _VRP_SHUTDOWN.match(line):
                actual.admin_up = False
                continue
            m = _VRP_DESCRIPTION.match(line)
            if m:
                actual.description = m.group(1)
                continue
            m = _VRP_IPV4_SECONDARY.match(line)
            if m:
                secundarias.append(_direccion_y_mascara_a_cidr(m.group(1), m.group(2)))
                continue
            m = _VRP_IPV4.match(line)
            if m:
                actual.ipv4_address = _direccion_y_mascara_a_cidr(m.group(1), m.group(2))
                continue
            m = _VRP_IPV6.match(line)
            if m:
                actual.ipv6_address = _normalizar_ipv6(m.group(1))
                continue
            m = _VRP_ACL_LINE.match(line)
            if m:
                direction = (m.group("dir1") or m.group("dir2") or "").lower()
                if direction == "inbound":
                    actual.acl_in = m.group("target")
                elif direction == "outbound":
                    actual.acl_out = m.group("target")
                continue
            m = _VRP_HELPER.match(line)
            if m:
                helpers.append(m.group(1))
                continue
            m = _VRP_BINDING.match(line)
            if m:
                binding_group = m.group(1)
                continue

        _cerrar_actual()

        usos = Counter(grupo_por_vlan.values())
        entradas = dhcp_group_entries or {}
        for svi in interfaces:
            grupo = grupo_por_vlan.get(svi.vlan_id)
            if grupo is not None:
                svi.dhcp_relay_layout = DhcpRelayLayout(
                    forma="grupo", grupo=grupo, indices=dict(entradas.get(grupo, {})),
                    exclusivo=usos[grupo] == 1 and grupo in entradas,
                )
            elif svi.vlan_id in directas:
                svi.dhcp_relay_layout = DhcpRelayLayout(forma="directa")
        return interfaces


def parse_vrp_dhcp_relay_groups(dhcp_config_output: str) -> dict[str, list[str]]:
    return HuaweiSVIParser.parse_dhcp_relay_groups(dhcp_config_output)


def parse_vrp_svis(
    config_output: str, brief_output: str, dhcp_groups: "dict[str, list[str]] | None" = None,
) -> list[SVI]:
    return HuaweiSVIParser.parse_svis(config_output, brief_output, dhcp_groups=dhcp_groups)


_IOS_ACL_HEADER = re.compile(r"^(?:Standard|Extended) IP access list (\S+)", re.IGNORECASE)


def parse_ios_acl_names(show_access_lists_output: str) -> list[str]:
    return [
        m.group(1) for raw in show_access_lists_output.splitlines()
        if (m := _IOS_ACL_HEADER.match(strip_ansi(raw).rstrip()))
    ]


_IOS_ACL_HEADER_FULL = re.compile(r"^(Standard|Extended) IP access list (\S+)", re.IGNORECASE)


def parse_ios_acls(show_access_lists_output: str) -> list[dict]:
    acls: list[dict] = []
    current: dict | None = None
    for raw in show_access_lists_output.splitlines():
        line = strip_ansi(raw).rstrip()
        if not line.strip():
            continue
        m = _IOS_ACL_HEADER_FULL.match(line)
        if m:
            current = {"name": m.group(2), "type": m.group(1).lower(), "rules": []}
            acls.append(current)
        elif current is not None and line[:1].isspace():
            current["rules"].append(line.strip())
        else:
            current = None
    return acls


_VRP_ACL_HEADER = re.compile(
    r"^(?:Basic|Advanced|Ethernet frame|User)\s+(?:Name\s+)?ACL\s+(.+?),", re.IGNORECASE,
)


def parse_vrp_acl_names(display_acl_all_output: str) -> list[str]:
    nombres = []
    for raw in display_acl_all_output.splitlines():
        m = _VRP_ACL_HEADER.match(strip_ansi(raw).rstrip())
        if m:
            nombres.append(m.group(1).split()[0])
    return nombres


_VRP_ACL_HEADER_FULL = re.compile(
    r"^(Basic|Advanced|Ethernet frame|User)\s+(?:Name\s+)?ACL\s+(\S+)(?:\s+\d+)?,", re.IGNORECASE,
)
_VRP_ACL_RULE_LINE = re.compile(r"^rule\s+\d+\b", re.IGNORECASE)


def parse_vrp_acls(display_acl_all_output: str) -> list[dict]:
    acls: list[dict] = []
    current: dict | None = None
    for raw in display_acl_all_output.splitlines():
        line = strip_ansi(raw).strip()
        if not line:
            continue
        m = _VRP_ACL_HEADER_FULL.match(line)
        if m:
            current = {"name": m.group(2), "type": m.group(1).lower(), "rules": []}
            acls.append(current)
        elif current is not None and _VRP_ACL_RULE_LINE.match(line):
            current["rules"].append(line)
    return acls
