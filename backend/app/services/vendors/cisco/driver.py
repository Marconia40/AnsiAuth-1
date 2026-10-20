from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING

from app.services.parsers._common import strip_known_preamble
from app.services.parsers.port_parser import CiscoPortParser
from app.services.vendors.base import VendorDriver

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.svi import SVI, DhcpRelayLayout
    from app.models.port import Puerto
    from app.models.vlan import VLAN
    from app.models.global_config import GlobalConfig

logger = logging.getLogger(__name__)

_PLAYBOOK = "vendors/cisco/run.yml"

_STATUS_INDEX = 0
_DESCRIPTION_INDEX = 1
_SWITCHPORT_INDEX = 2
_STORM_INDEX = 3
_RUNNING_CONFIG_INDEX = 4

_LOG_WINDOW_DAYS = 7

_RUNNING_CONFIG_PREAMBLE = [
    r"^Building configuration\.\.\.\s*$",
    r"^Current configuration\s*:.*bytes\s*$",
    r"^!\s*Last configuration change.*$",
    r"^!\s*NVRAM config last updated.*$",
]


class CiscoVendor(VendorDriver):
    _NETWORK_OS = "ios"
    _PLAYBOOK = _PLAYBOOK


    def resolver_create_vlan(self, vlan_id: int, name: str) -> tuple[str, "str | None", dict]:
        return "create_vlan", None, {"vlan_id": vlan_id, "name": name}

    def create_vlan(self, vlan_id: int, name: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_create_vlan(vlan_id, name)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_delete_vlan(self, vlan_id: int) -> tuple[str, "str | None", dict]:
        return "delete_vlan", None, {"vlan_id": vlan_id}

    def delete_vlan(self, vlan_id: int, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_delete_vlan(vlan_id)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_update_vlan(self, vlan_id: int, name: str) -> tuple[str, "str | None", dict]:
        return "update_vlan", None, {"vlan_id": vlan_id, "name": name}

    def update_vlan(self, vlan_id: int, name: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_update_vlan(vlan_id, name)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def save_config(self, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("save_config", {}, device, password)


    def list_vlans(self, device: Device, password: str) -> list[VLAN]:
        commands = self._cargar_comandos()["list_vlans"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        from app.services.parsers.vlan_parser import parse_vlan_brief
        vlans = parse_vlan_brief(stdouts[0])
        return vlans

    def get_vlans(self, device: Device, password: str) -> list[VLAN]:
        return self.list_vlans(device, password)


    def list_ports(self, device: Device, password: str) -> list[Puerto]:
        commands = self._cargar_comandos()["list_ports"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password, partial_ok=True)
        stdouts = self._filter_unsupported(stdouts, commands, device)
        status = stdouts[_STATUS_INDEX] if len(stdouts) > _STATUS_INDEX else ""
        description = stdouts[_DESCRIPTION_INDEX] if len(stdouts) > _DESCRIPTION_INDEX else ""
        switchport = stdouts[_SWITCHPORT_INDEX] if len(stdouts) > _SWITCHPORT_INDEX else ""
        storm = stdouts[_STORM_INDEX] if len(stdouts) > _STORM_INDEX else ""
        running_config = stdouts[_RUNNING_CONFIG_INDEX] if len(stdouts) > _RUNNING_CONFIG_INDEX else ""
        try:
            ports = CiscoPortParser.parse_ports(status, description, switchport, storm, running_config)
        except Exception as exc:
            raise RuntimeError(f"Cannot determine port state on device '{device.name}': {exc}") from exc
        return ports


    def resolver_update_port_description(self, interface: str, description: str) -> tuple[str, "str | None", dict]:
        variant = "clear" if self._is_description_empty(description) else "set"
        return "update_port_description", variant, {"interface": interface, "description": description}

    def update_port_description(self, interface: str, description: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_update_port_description(interface, description)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_port_admin_state(self, interface: str, enabled: bool) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        return "set_port_admin_state", variant, {"interface": interface}

    def set_port_admin_state(self, interface: str, enabled: bool, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_port_admin_state(interface, enabled)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_port_access_vlan(self, interface: str, vlan_id: int) -> tuple[str, "str | None", dict]:
        return "set_port_access_vlan", None, {"interface": interface, "vlan_id": vlan_id}

    def set_port_access_vlan(self, interface: str, vlan_id: int, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_port_access_vlan(interface, vlan_id)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_trunk_pvid_vlan(self, interface: str, vlan_id: int) -> tuple[str, "str | None", dict]:
        return "set_trunk_pvid_vlan", None, {"interface": interface, "vlan_id": vlan_id}

    def set_trunk_pvid_vlan(self, interface: str, vlan_id: int, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_trunk_pvid_vlan(interface, vlan_id)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_trunk_allowed_vlans(self, interface: str, vlan_list: list[int]) -> tuple[str, "str | None", dict]:
        vlan_str = self._compress_vlans_cisco(sorted(set(vlan_list)))
        return "set_trunk_allowed_vlans", None, {"interface": interface, "allowed_vlans": vlan_str}

    def set_trunk_allowed_vlans(self, interface: str, vlan_list: list[int], device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_trunk_allowed_vlans(interface, vlan_list)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_trunk_vlans_delta(
        self, interface: str, add: list[int], remove: list[int],
    ) -> tuple[str, "str | None", dict]:
        add = sorted(set(add or []))
        remove = sorted(set(remove or []))
        if not add and not remove:
            raise ValueError("set_trunk_vlans_delta necesita al menos una VLAN a agregar o a quitar")
        variant = "both" if add and remove else ("add" if add else "remove")
        vars = {
            "interface": interface,
            "add_vlans": self._compress_vlans_cisco(add),
            "remove_vlans": self._compress_vlans_cisco(remove),
        }
        return "set_trunk_vlans_delta", variant, vars

    def resolver_set_trunk_config_delta(
        self, interface: str, pvid: "int | None", add: list[int], remove: list[int],
    ) -> tuple[str, "str | None", dict]:
        add = sorted(set(add or []))
        remove = sorted(set(remove or []))
        if pvid is None and not add and not remove:
            raise ValueError("set_trunk_config_delta necesita un PVID o al menos una VLAN a agregar o quitar")
        lineas: list[str] = []
        if add:
            lineas.append(f"switchport trunk allowed vlan add {self._compress_vlans_cisco(add)}")
        if pvid is not None:
            lineas.append(f"switchport trunk native vlan {int(pvid)}")
        if remove:
            lineas.append(f"switchport trunk allowed vlan remove {self._compress_vlans_cisco(remove)}")
        return "set_trunk_config_delta", None, {"interface": interface, "trunk_lines": lineas}

    def resolver_set_port_poe(self, interface: str, enabled: bool) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        return "set_port_poe", variant, {"interface": interface}

    def set_port_poe(self, interface: str, enabled: bool, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_port_poe(interface, enabled)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_storm_control(
        self, interface: str, enabled: bool, threshold: "float | None", action: str = "shutdown", trap: bool = True,
    ) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        action_lines = (
            (["storm-control action shutdown"] if action == "shutdown" else [])
            + (["storm-control action trap"] if trap else [])
        )
        return "set_storm_control", variant, {
            "interface": interface, "threshold": threshold, "action_lines": action_lines,
        }

    def set_storm_control(
        self, interface: str, enabled: bool, threshold: "float | None", action: str, trap: bool,
        device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_storm_control(interface, enabled, threshold, action, trap)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_reset_port(self, interface: str) -> tuple[str, "str | None", dict]:
        return "reset_port", None, {"interface": interface}

    def reset_port(self, interface: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_reset_port(interface)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_access_mode(
        self, interface: str, vlan_id: int, *, viene_de_trunk_con_vlans: bool = True,
    ) -> tuple[str, "str | None", dict]:
        return "set_access_mode", None, {"interface": interface, "vlan_id": vlan_id}

    def set_access_mode(
        self, interface: str, vlan_id: int, device: Device, password: str,
        *, viene_de_trunk_con_vlans: bool = True,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_access_mode(
            interface, vlan_id, viene_de_trunk_con_vlans=viene_de_trunk_con_vlans,
        )
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_trunk_mode(
        self, interface: str, native_vlan: int, vlan_list: list[int],
    ) -> tuple[str, "str | None", dict]:
        vlan_str = self._compress_vlans_cisco(sorted(set(vlan_list)))
        return "set_trunk_mode", None, {"interface": interface, "native_vlan": native_vlan, "allowed_vlans": vlan_str}

    def set_trunk_mode(
        self, interface: str, native_vlan: int, vlan_list: list[int], device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_trunk_mode(interface, native_vlan, vlan_list)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)


    def _compress_vlans_cisco(self, vlans: list[int]) -> str:
        parts = []
        for s, e in self._compress_to_ranges(vlans):
            parts.append(f"{s}-{e}" if s != e else str(s))
        return ",".join(parts)


    def create_svi(self, vlan_id: int, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("create_svi", {"vlan_id": vlan_id}, device, password)

    def delete_svi(self, vlan_id: int, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("delete_svi", {"vlan_id": vlan_id}, device, password)


    def resolver_set_svi_admin_state(self, vlan_id: int, enabled: bool) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        return "set_svi_admin_state", variant, {"vlan_id": vlan_id}

    def set_svi_admin_state(self, vlan_id: int, enabled: bool, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_svi_admin_state(vlan_id, enabled)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_description(self, vlan_id: int, description: str) -> tuple[str, "str | None", dict]:
        variant = "clear" if self._is_description_empty(description) else "set"
        return "set_svi_description", variant, {"vlan_id": vlan_id, "description": description}

    def set_svi_description(self, vlan_id: int, description: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_svi_description(vlan_id, description)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_ipv4(self, vlan_id: int, ipv4_address: "str | None") -> tuple[str, "str | None", dict]:
        variant = "clear" if not ipv4_address else "set"
        addr, mask = self._cidr_a_direccion_y_mascara(ipv4_address)
        return "set_svi_ipv4", variant, {"vlan_id": vlan_id, "ipv4_addr": addr, "ipv4_mask": mask}

    def set_svi_ipv4(self, vlan_id: int, ipv4_address: "str | None", device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_svi_ipv4(vlan_id, ipv4_address)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_ipv4_secondary(
        self, vlan_id: int, ipv4_address: "str | None", previous_ipv4_address: "str | None",
    ) -> tuple[str, "str | None", dict]:
        variant = "clear" if not ipv4_address else "set"
        addr, mask = self._cidr_a_direccion_y_mascara(ipv4_address if ipv4_address else previous_ipv4_address)
        return "set_svi_ipv4_secondary", variant, {"vlan_id": vlan_id, "ipv4_addr": addr, "ipv4_mask": mask}

    def set_svi_ipv4_secondary(
        self, vlan_id: int, ipv4_address: "str | None", previous_ipv4_address: "str | None",
        device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_svi_ipv4_secondary(vlan_id, ipv4_address, previous_ipv4_address)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_ipv6(self, vlan_id: int, ipv6_address: "str | None") -> tuple[str, "str | None", dict]:
        variant = "clear" if not ipv6_address else "set"
        return "set_svi_ipv6", variant, {"vlan_id": vlan_id, "ipv6_address": ipv6_address or ""}

    def set_svi_ipv6(self, vlan_id: int, ipv6_address: "str | None", device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_svi_ipv6(vlan_id, ipv6_address)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_acl(
        self, vlan_id: int, direction: str, acl_name: "str | None", *, current_acl_name: "str | None" = None,
    ) -> tuple[str, "str | None", dict]:
        variant = "clear" if not acl_name else "set"
        return "set_svi_acl", variant, {"vlan_id": vlan_id, "direction": direction, "acl_name": acl_name or ""}

    def set_svi_acl(
        self, vlan_id: int, direction: str, acl_name: "str | None", device: Device, password: str,
        *, current_acl_name: "str | None" = None,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_svi_acl(vlan_id, direction, acl_name)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_dhcp_relay(
        self, vlan_id: int, servers: list[str],
    ) -> "tuple[str, str | None, dict]":
        return "set_svi_dhcp_relay", None, {"vlan_id": vlan_id, "servers": servers}

    def resolver_set_svi_dhcp_relay_delta(
        self, vlan_id: int, add: list[str], remove: list[str], servers_final: list[str],
        layout: "DhcpRelayLayout | None" = None, indices_previos: "dict[str, int] | None" = None,
    ) -> "tuple[str, str | None, dict]":
        if not add and not remove:
            raise ValueError("set_svi_dhcp_relay_delta needs at least one server to add or remove")
        relay_lines = [f"ip helper-address {ip}" for ip in add] + [
            f"no ip helper-address {ip}" for ip in remove
        ]
        return "set_svi_dhcp_relay_delta", None, {"vlan_id": vlan_id, "relay_lines": relay_lines}

    def set_svi_dhcp_relay(
        self, vlan_id: int, servers: list[str], device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_svi_dhcp_relay(vlan_id, servers)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def get_svis(self, device: Device, password: str) -> list[SVI]:
        commands = self._cargar_comandos()["get_svis"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        from app.services.parsers.svi_parser import CiscoSVIParser
        running_config = stdouts[0] if len(stdouts) > 0 else ""
        brief = stdouts[1] if len(stdouts) > 1 else ""
        return CiscoSVIParser.parse_svis(running_config, brief)

    def read_core_state(self, device: Device, password: str):
        from app.services.parsers.svi_parser import CiscoSVIParser, bloques_interface_vlan
        from app.services.parsers.vlan_parser import parse_vlan_brief

        cmds = self._cargar_comandos()
        vlan_cmds = list(cmds["list_vlans"]["primary"]["commands"])
        port_cmds = list(cmds["list_ports"]["primary"]["commands"])
        svi_cmds = [
            c for c in cmds["get_svis"]["primary"]["commands"]
            if not c.startswith("show running-config")
        ]

        combined = vlan_cmds + port_cmds + svi_cmds
        stdouts = self._leer(combined, device, password, partial_ok=True)
        stdouts = self._filter_unsupported(stdouts, combined, device)

        v_end = len(vlan_cmds)
        p_end = v_end + len(port_cmds)
        vlan_out = stdouts[:v_end]
        port_out = stdouts[v_end:p_end]
        svi_out = stdouts[p_end:]

        vlans = parse_vlan_brief(vlan_out[0]) if vlan_out else []

        status = port_out[_STATUS_INDEX] if len(port_out) > _STATUS_INDEX else ""
        description = port_out[_DESCRIPTION_INDEX] if len(port_out) > _DESCRIPTION_INDEX else ""
        switchport = port_out[_SWITCHPORT_INDEX] if len(port_out) > _SWITCHPORT_INDEX else ""
        storm = port_out[_STORM_INDEX] if len(port_out) > _STORM_INDEX else ""
        running_config_ports = port_out[_RUNNING_CONFIG_INDEX] if len(port_out) > _RUNNING_CONFIG_INDEX else ""
        try:
            ports = CiscoPortParser.parse_ports(status, description, switchport, storm, running_config_ports)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot determine port state on device '{device.name}': {exc}",
            ) from exc

        brief = svi_out[0] if len(svi_out) > 0 else ""
        svis = CiscoSVIParser.parse_svis(bloques_interface_vlan(running_config_ports), brief)

        return vlans, ports, svis

    def list_acl_names(self, device: Device, password: str) -> list[str]:
        commands = self._cargar_comandos()["list_acls"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        from app.services.parsers.svi_parser import parse_ios_acl_names
        return parse_ios_acl_names(stdouts[0] if stdouts else "")

    def list_acls(self, device: Device, password: str) -> list[dict]:
        commands = self._cargar_comandos()["list_acls"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        from app.services.parsers.svi_parser import parse_ios_acls
        return parse_ios_acls(stdouts[0] if stdouts else "")

    def _formatear_endpoint_acl(self, endpoint: dict) -> str:
        if endpoint.get("any"):
            return "any"
        if endpoint.get("host"):
            return f"host {endpoint['host']}"
        network, wildcard = self._red_y_wildcard(endpoint["network"])
        return f"{network} {wildcard}"

    def formatear_regla_acl(self, rule: dict) -> str:
        partes = [
            rule["action"], rule["protocol"],
            self._formatear_endpoint_acl(rule["source"]),
            self._formatear_endpoint_acl(rule["destination"]),
        ]
        port = rule.get("port")
        if port:
            if port["operator"] == "range":
                partes.append(f"range {port['value']} {port['value2']}")
            else:
                partes.append(f"eq {port['value']}")
        return " ".join(partes)

    def create_or_update_acl(self, name: str, rule_lines: list[str], device: Device, password: str) -> dict:
        return self._aplicar_desde_template(
            "create_or_update_acl", {"name": name, "rule_lines": rule_lines}, device, password,
        )

    def remove_acl_rules(self, name: str, rule_lines: list[str], device: Device, password: str) -> dict:
        return self._aplicar_desde_template(
            "remove_acl_rules", {"name": name, "rule_lines": rule_lines}, device, password,
        )

    def delete_acl(self, name: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("delete_acl", {"name": name}, device, password)

    def get_global_config(self, device: Device, password: str) -> "GlobalConfig":
        commands = self._cargar_comandos()["get_global_config"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        version_output = stdouts[0] if len(stdouts) > 0 else ""
        hostname_output = stdouts[1] if len(stdouts) > 1 else ""
        community_output = stdouts[2] if len(stdouts) > 2 else ""
        route_output = stdouts[3] if len(stdouts) > 3 else ""
        running_config = stdouts[4] if len(stdouts) > 4 else ""

        snmp_commands = self._cargar_comandos()["get_snmp_status"]["primary"]["commands"]
        try:
            self._leer(snmp_commands, device, password)
            snmp_enabled = True
        except RuntimeError as exc:
            if "snmp agent not enabled" in str(exc).lower():
                snmp_enabled = False
            else:
                raise

        try:
            acls = self.list_acls(device, password)
        except RuntimeError:
            logger.exception("get_global_config: list_acls failed on device=%s, continuing without ACLs", device.name)
            acls = None

        from app.services.parsers.global_config_parser import CiscoGlobalConfigParser
        config = CiscoGlobalConfigParser.parse(
            version_output=version_output, hostname_output=hostname_output,
            community_output=community_output, route_output=route_output,
            running_config_output=running_config, snmp_enabled=snmp_enabled,
        )
        config.device = device.name
        config.acls = acls
        config.running_config = strip_known_preamble(running_config, _RUNNING_CONFIG_PREAMBLE, separador="!") or None
        return config

    def set_hostname(self, hostname: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("set_hostname", {"hostname": hostname}, device, password)

    def set_snmp(self, cambios: dict, device: Device, password: str) -> dict:
        if "version" in cambios:
            logger.info(
                "CiscoVendor.set_snmp: 'version' has no distinct IOS community-based "
                "command, ignoring for device=%s",
                device.name,
            )
        resultados = []
        if "community" in cambios:
            resultados.append(
                self._aplicar_desde_template(
                    "set_snmp_community", {"community": cambios["community"]}, device, password,
                )
            )
        if "trap_source" in cambios:
            resultados.append(
                self._aplicar_desde_template(
                    "set_snmp_trap_source", {"interface": cambios["trap_source"]}, device, password,
                )
            )
        if "trap_host" in cambios:
            resultados.append(
                self._aplicar_desde_template(
                    "set_snmp_trap_host",
                    {
                        "host": cambios["trap_host"], "version": cambios["trap_version"],
                        "community": cambios["trap_host_community"],
                    },
                    device, password,
                )
            )
        return self._combinar_resultados(resultados)

    def remove_snmp_trap_host(
        self, host: str, device: Device, password: str, *, community: "str | None" = None,
    ) -> dict:
        if not community:
            raise ValueError(
                "CiscoVendor.remove_snmp_trap_host: 'community' is required -- "
                "'no snmp-server host {ip}' alone is rejected by IOS as an incomplete command"
            )
        return self._aplicar_desde_template(
            "remove_snmp_trap_host", {"host": host, "community": community}, device, password,
        )

    def add_log_server(self, server: str, level: "str | None", device: Device, password: str) -> dict:
        if level:
            return self._aplicar_desde_template(
                "set_log_host_and_level", {"log_server": server, "log_level": level}, device, password,
            )
        return self._aplicar_desde_template("set_log_host", {"log_server": server}, device, password)

    def remove_log_server(self, server: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("remove_log_host", {"log_server": server}, device, password)

    def get_arp_table(self, device: Device, password: str) -> list[dict]:
        from app.services.parsers.arp_mac_parser import parse_cisco_arp

        raw = self._leer(["show arp"], device, password)[0]
        return parse_cisco_arp(raw)

    def get_mac_table(self, device: Device, password: str) -> list[dict]:
        from app.services.parsers.arp_mac_parser import parse_cisco_mac

        raw = self._leer(["show mac address-table"], device, password)[0]
        return parse_cisco_mac(raw)

    def get_log_buffer(self, device: Device, password: str) -> str:
        extravars = {
            "commands": ["show logging | exclude CFGLOG_LOGGEDCMD"],
            "tolerate_command_errors": True,
        }
        result = self._ejecutar(extravars, device, password)
        stdouts = result.get("stdouts") or []
        if result.get("rc") == 0:
            if not stdouts:
                raise RuntimeError(f"Cannot read state on device '{device.name}': no command output returned")
            return stdouts[0].strip()
        if not stdouts or not stdouts[0]:
            error = result.get("stderr") or result.get("stdout") or "playbook exited non-zero"
            raise RuntimeError(f"Cannot read state on device '{device.name}': {error}")
        logger.warning(
            "%s: get_log_buffer full read cut off on device=%s (buffer too large for 1 session) -- "
            "falling back to a recent-dates-only read",
            type(self).__name__, device.name,
        )
        return self._get_log_buffer_recent_dates(device, password)

    def _get_log_buffer_recent_dates(self, device: Device, password: str) -> str:
        from datetime import datetime, timedelta

        import re

        clock_raw = self._leer(["show clock"], device, password)[0].strip().lstrip("*")
        m = re.search(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})", clock_raw)
        if m is None:
            raise RuntimeError(f"Cannot parse 'show clock' output on device '{device.name}': {clock_raw!r}")
        mes, dia, anio = m.groups()
        hoy = datetime.strptime(f"{mes} {dia} {anio}", "%b %d %Y")
        dias = [(hoy - timedelta(days=i)).strftime("%b %-d") for i in range(_LOG_WINDOW_DAYS)]
        patron = "|".join(dias)
        raw = self._leer(
            [f"show logging | include ^({patron}) "], device, password, partial_ok=True,
        )[0]
        return raw.strip()

    def search_mac_table(self, pattern: str, device: Device, password: str) -> list[dict]:
        from app.services.parsers.arp_mac_parser import parse_cisco_mac

        raw = self._leer([f"show mac address-table | include {pattern}"], device, password)[0]
        return parse_cisco_mac(raw)

    def set_route(self, destination: str, next_hop: str, device: Device, password: str) -> dict:
        network, mask = self._red_y_mascara(destination)
        return self._aplicar_desde_template(
            "set_route", {"network": network, "mask": mask, "next_hop": next_hop}, device, password,
        )

    def remove_route(self, destination: str, next_hop: str, device: Device, password: str) -> dict:
        network, mask = self._red_y_mascara(destination)
        return self._aplicar_desde_template(
            "remove_route", {"network": network, "mask": mask, "next_hop": next_hop}, device, password,
        )

    def add_ntp_server(self, server: str, prefer: bool, device: Device, password: str) -> dict:
        op_key = "add_ntp_with_prefer" if prefer else "add_ntp"
        return self._aplicar_desde_template(op_key, {"server": server}, device, password)

    def remove_ntp_server(self, server: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("remove_ntp", {"server": server}, device, password)

    def add_dns_server(self, server: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("add_dns", {"server": server}, device, password)

    def remove_dns_server(self, server: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("remove_dns", {"server": server}, device, password)

    def set_dns_domain(self, domain: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("set_dns_domain", {"domain": domain}, device, password)

    @staticmethod
    def _cidr_a_direccion_y_mascara(cidr: "str | None") -> tuple[str, str]:
        if not cidr:
            return "", ""
        interfaz = ipaddress.ip_interface(cidr)
        return str(interfaz.ip), str(interfaz.netmask)
