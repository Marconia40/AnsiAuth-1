from __future__ import annotations

import ipaddress
import logging
import re
from typing import TYPE_CHECKING

from app.services.parsers._common import strip_known_preamble
from app.services.parsers.port_parser import HuaweiPortParser, expandir_nombre_interfaz
from app.services.vendors.base import VendorDriver

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.svi import SVI, DhcpRelayLayout
    from app.models.port import Puerto
    from app.models.vlan import VLAN
    from app.models.global_config import GlobalConfig

logger = logging.getLogger(__name__)

_PLAYBOOK = "vendors/huawei/run.yml"

_BRIEF_INDEX = 0
_DESCRIPTION_INDEX = 1
_PORT_VLAN_INDEX = 2
_STORM_INDEX = 3

_RUNNING_CONFIG_PREAMBLE = [
    r"^!Software Version.*$",
]


class HuaweiVendor(VendorDriver):
    _NETWORK_OS = "community.network.ce"
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
        from app.services.parsers.vlan_parser import parse_vrp_vlan_display
        return parse_vrp_vlan_display(stdouts[0])

    def get_vlans(self, device: Device, password: str) -> list[VLAN]:
        return self.list_vlans(device, password)


    def list_ports(self, device: Device, password: str) -> list[Puerto]:
        commands = self._cargar_comandos()["list_ports"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        brief = stdouts[_BRIEF_INDEX] if len(stdouts) > _BRIEF_INDEX else ""
        description = stdouts[_DESCRIPTION_INDEX] if len(stdouts) > _DESCRIPTION_INDEX else ""
        port_vlan = stdouts[_PORT_VLAN_INDEX] if len(stdouts) > _PORT_VLAN_INDEX else ""
        storm = stdouts[_STORM_INDEX] if len(stdouts) > _STORM_INDEX else ""
        try:
            ports = HuaweiPortParser.parse_ports(brief, description, port_vlan, storm)
        except Exception as exc:
            raise RuntimeError(f"Cannot determine port state on device '{device.name}': {exc}") from exc
        return ports


    def resolver_update_port_description(self, interface: str, description: str) -> tuple[str, "str | None", dict]:
        variant = "clear" if self._is_description_empty(description) else "set"
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface), "description": description}
        return "update_port_description", variant, vars

    def update_port_description(self, interface: str, description: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_update_port_description(interface, description)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_port_admin_state(self, interface: str, enabled: bool) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface)}
        return "set_port_admin_state", variant, vars

    def set_port_admin_state(self, interface: str, enabled: bool, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_port_admin_state(interface, enabled)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_port_access_vlan(self, interface: str, vlan_id: int) -> tuple[str, "str | None", dict]:
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface), "vlan_id": vlan_id}
        return "set_port_access_vlan", None, vars

    def set_port_access_vlan(self, interface: str, vlan_id: int, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_port_access_vlan(interface, vlan_id)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_trunk_pvid_vlan(self, interface: str, vlan_id: int) -> tuple[str, "str | None", dict]:
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface), "vlan_id": vlan_id}
        return "set_trunk_pvid_vlan", None, vars

    def set_trunk_pvid_vlan(self, interface: str, vlan_id: int, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_trunk_pvid_vlan(interface, vlan_id)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_trunk_allowed_vlans(self, interface: str, vlan_list: list[int]) -> tuple[str, "str | None", dict]:
        vlan_str = self._compress_vlans_huawei(sorted(set(vlan_list)))
        vars = {
            "interface": interface, "interface_full": expandir_nombre_interfaz(interface),
            "allowed_vlans": vlan_str,
        }
        return "set_trunk_allowed_vlans", None, vars

    def set_trunk_allowed_vlans(self, interface: str, vlan_list: list[int], device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_trunk_allowed_vlans(interface, vlan_list)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    _MAX_ITEMS_ALLOW_PASS_POR_LINEA = 10

    def _lista_allow_pass(self, prefijo: str, vlans: list[int]) -> list[str]:
        items = [f"{s} to {e}" if s != e else str(s) for s, e in self._compress_to_ranges(vlans)]
        n = self._MAX_ITEMS_ALLOW_PASS_POR_LINEA
        return [f"{prefijo} {' '.join(items[i:i + n])}" for i in range(0, len(items), n)]

    def _lineas_allow_pass(self, prefijo: str, vlans: list[int]) -> str:
        return "\n".join(self._lista_allow_pass(prefijo, vlans))

    def resolver_set_trunk_vlans_delta(
        self, interface: str, add: list[int], remove: list[int],
    ) -> tuple[str, "str | None", dict]:
        add = sorted(set(add or []))
        remove = sorted(set(remove or []))
        if not add and not remove:
            raise ValueError("set_trunk_vlans_delta necesita al menos una VLAN a agregar o a quitar")
        variant = "both" if add and remove else ("add" if add else "remove")
        vars = {
            "interface": interface, "interface_full": expandir_nombre_interfaz(interface),
            "add_lines": self._lineas_allow_pass("port trunk allow-pass vlan", add),
            "remove_lines": self._lineas_allow_pass("undo port trunk allow-pass vlan", remove),
        }
        return "set_trunk_vlans_delta", variant, vars

    def resolver_set_trunk_config_delta(
        self, interface: str, pvid: "int | None", add: list[int], remove: list[int],
    ) -> tuple[str, "str | None", dict]:
        add = sorted(set(add or []))
        remove = sorted(set(remove or []))
        if pvid is None and not add and not remove:
            raise ValueError("set_trunk_config_delta necesita un PVID o al menos una VLAN a agregar o quitar")
        lineas = self._lista_allow_pass("port trunk allow-pass vlan", add)
        if pvid is not None:
            lineas.append(f"port trunk pvid vlan {int(pvid)}")
        lineas += self._lista_allow_pass("undo port trunk allow-pass vlan", remove)
        vars = {
            "interface": interface, "interface_full": expandir_nombre_interfaz(interface),
            "trunk_lines": lineas,
        }
        return "set_trunk_config_delta", None, vars

    def resolver_set_port_poe(self, interface: str, enabled: bool) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface)}
        return "set_port_poe", variant, vars

    def set_port_poe(self, interface: str, enabled: bool, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_set_port_poe(interface, enabled)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_storm_control(
        self, interface: str, enabled: bool, threshold: "float | None", action: str = "shutdown", trap: bool = True,
    ) -> tuple[str, "str | None", dict]:
        variant = "enabled" if enabled else "disabled"
        accion_vrp = "shutdown" if action == "shutdown" else "block"
        action_lines = [f"storm control action {accion_vrp}"] + (
            ["storm control enable trap"] if trap else []
        )
        action_lines_dash = [f"storm-control action {accion_vrp}"] + (
            ["storm-control enable trap"] if trap else []
        )
        vars = {
            "interface": interface, "interface_full": expandir_nombre_interfaz(interface),
            "threshold": int(threshold) if threshold is not None else None,
            "action_lines": action_lines, "action_lines_dash": action_lines_dash,
        }
        return "set_storm_control", variant, vars

    def set_storm_control(
        self, interface: str, enabled: bool, threshold: "float | None", action: str, trap: bool,
        device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_storm_control(interface, enabled, threshold, action, trap)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_reset_port(self, interface: str) -> tuple[str, "str | None", dict]:
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface)}
        return "reset_port", None, vars

    def reset_port(self, interface: str, device: Device, password: str) -> dict:
        op_key, variant, vars = self.resolver_reset_port(interface)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)


    def resolver_set_access_mode(
        self, interface: str, vlan_id: int, *, viene_de_trunk_con_vlans: bool = True,
    ) -> tuple[str, "str | None", dict]:
        vars = {"interface": interface, "interface_full": expandir_nombre_interfaz(interface), "vlan_id": vlan_id}
        variant = "con_confirmacion" if viene_de_trunk_con_vlans else "sin_confirmacion"
        return "set_access_mode", variant, vars

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
        vlan_str = self._compress_vlans_huawei(sorted(set(vlan_list)))
        vars = {
            "interface": interface, "interface_full": expandir_nombre_interfaz(interface),
            "native_vlan": native_vlan, "allowed_vlans": vlan_str,
        }
        return "set_trunk_mode", None, vars

    def set_trunk_mode(
        self, interface: str, native_vlan: int, vlan_list: list[int], device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_trunk_mode(interface, native_vlan, vlan_list)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)


    def _compress_vlans_huawei(self, vlans: list[int]) -> str:
        parts = []
        for s, e in self._compress_to_ranges(vlans):
            parts.append(f"{s} to {e}" if s != e else str(s))
        return " ".join(parts)


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

    def set_svi_acl(
        self, vlan_id: int, direction: str, acl_name: "str | None", device: Device, password: str,
        *, current_acl_name: "str | None" = None,
    ) -> dict:
        if not acl_name and not current_acl_name:
            return {"rc": 0, "stdout": "", "stderr": "", "success": True}
        op_key, variant, vars = self.resolver_set_svi_acl(
            vlan_id, direction, acl_name, current_acl_name=current_acl_name,
        )
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    def resolver_set_svi_acl(
        self, vlan_id: int, direction: str, acl_name: "str | None", *, current_acl_name: "str | None" = None,
    ) -> tuple[str, "str | None", dict]:
        if not acl_name:
            variant = "clear_numeric" if (current_acl_name or "").isdigit() else "clear_named"
            template_acl_name = current_acl_name or ""
        elif acl_name.isdigit():
            variant = "set_numeric"
            template_acl_name = acl_name
        else:
            variant = "set_named"
            template_acl_name = acl_name
        return "set_svi_acl", variant, {"vlan_id": vlan_id, "direction": direction, "acl_name": template_acl_name}

    def resolver_set_svi_dhcp_relay(
        self, vlan_id: int, servers: list[str],
    ) -> "tuple[str, str | None, dict]":
        return "set_svi_dhcp_relay", None, {"vlan_id": vlan_id, "servers": servers}

    def resolver_set_svi_dhcp_relay_delta(
        self, vlan_id: int, add: list[str], remove: list[str], servers_final: list[str],
        layout: "DhcpRelayLayout | None" = None, indices_previos: "dict[str, int] | None" = None,
    ) -> "tuple[str, str | None, dict]":
        lineas = self._lineas_relay_delta(vlan_id, add, remove, servers_final, layout, indices_previos)
        if lineas is None:
            return self.resolver_set_svi_dhcp_relay(vlan_id, list(servers_final))
        return "set_svi_dhcp_relay_delta", None, {"vlan_id": vlan_id, "relay_lines": lineas}

    @staticmethod
    def _lineas_relay_delta(
        vlan_id: int, add: list[str], remove: list[str], servers_final: list[str],
        layout: "DhcpRelayLayout | None", indices_previos: "dict[str, int] | None",
    ) -> "list[str] | None":
        if layout is None or not (add or remove):
            return None
        if layout.forma == "grupo":
            if not layout.exclusivo or not layout.grupo:
                return None
            lineas = [f"dhcp relay server group {layout.grupo}"]
            for ip, indice in layout.asignar_indices(list(add), indices_previos).items():
                lineas.append(f"server {ip} {indice}")
            lineas += [f"undo server {ip}" for ip in remove]
            if not servers_final:
                lineas += [
                    "quit", f"interface Vlanif{vlan_id}",
                    "undo dhcp select relay", "undo dhcp relay binding server group",
                ]
            return lineas
        if layout.forma == "directa" and servers_final:
            return (
                [f"interface Vlanif{vlan_id}"]
                + [f"dhcp relay server-ip {ip}" for ip in add]
                + [f"undo dhcp relay server-ip {ip}" for ip in remove]
            )
        return None

    def set_svi_dhcp_relay(
        self, vlan_id: int, servers: list[str], device: Device, password: str,
    ) -> dict:
        op_key, variant, vars = self.resolver_set_svi_dhcp_relay(vlan_id, servers)
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    _VLANIF_BRIEF_RE = re.compile(r"^Vlanif(\d+)\b", re.MULTILINE)

    def get_svis(self, device: Device, password: str) -> list[SVI]:
        brief = self._leer(["display ip interface brief"], device, password)[0]
        vlan_ids = sorted({int(m) for m in self._VLANIF_BRIEF_RE.findall(brief)})
        from app.services.parsers.svi_parser import HuaweiSVIParser
        if not vlan_ids:
            dhcp_config = self._leer(["display current-configuration configuration dhcp"], device, password)[0]
            return HuaweiSVIParser.parse_svis(
                "", brief,
                dhcp_groups=HuaweiSVIParser.parse_dhcp_relay_groups(dhcp_config),
                dhcp_group_entries=HuaweiSVIParser.parse_dhcp_relay_group_entries(dhcp_config),
            )
        per_iface_commands = [f"display current-configuration interface Vlanif{vid}" for vid in vlan_ids]
        per_iface_commands.append("display current-configuration configuration dhcp")
        outputs = self._leer(per_iface_commands, device, password)
        config = "\n".join(outputs[:-1])
        return HuaweiSVIParser.parse_svis(
            config, brief,
            dhcp_groups=HuaweiSVIParser.parse_dhcp_relay_groups(outputs[-1]),
            dhcp_group_entries=HuaweiSVIParser.parse_dhcp_relay_group_entries(outputs[-1]),
        )

    def read_core_state(self, device: Device, password: str):
        from app.services.parsers.svi_parser import HuaweiSVIParser
        from app.services.parsers.vlan_parser import parse_vrp_vlan_display

        cmds = self._cargar_comandos()
        vlan_cmds = list(cmds["list_vlans"]["primary"]["commands"])
        port_cmds = list(cmds["list_ports"]["primary"]["commands"])

        session_a = vlan_cmds + port_cmds + ["display ip interface brief"]
        stdouts_a = self._leer(session_a, device, password)

        v_end = len(vlan_cmds)
        p_end = v_end + len(port_cmds)
        vlan_out = stdouts_a[:v_end]
        port_out = stdouts_a[v_end:p_end]
        brief = stdouts_a[p_end] if len(stdouts_a) > p_end else ""

        vlans = parse_vrp_vlan_display(vlan_out[0]) if vlan_out else []

        port_brief = port_out[_BRIEF_INDEX] if len(port_out) > _BRIEF_INDEX else ""
        description = port_out[_DESCRIPTION_INDEX] if len(port_out) > _DESCRIPTION_INDEX else ""
        port_vlan = port_out[_PORT_VLAN_INDEX] if len(port_out) > _PORT_VLAN_INDEX else ""
        storm = port_out[_STORM_INDEX] if len(port_out) > _STORM_INDEX else ""
        try:
            ports = HuaweiPortParser.parse_ports(port_brief, description, port_vlan, storm)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot determine port state on device '{device.name}': {exc}",
            ) from exc

        vlan_ids = sorted({int(m) for m in self._VLANIF_BRIEF_RE.findall(brief)})
        if not vlan_ids:
            dhcp_config = self._leer(
                ["display current-configuration configuration dhcp"], device, password,
            )[0]
            svis = HuaweiSVIParser.parse_svis(
                "", brief,
                dhcp_groups=HuaweiSVIParser.parse_dhcp_relay_groups(dhcp_config),
                dhcp_group_entries=HuaweiSVIParser.parse_dhcp_relay_group_entries(dhcp_config),
            )
        else:
            per_iface_commands = [
                f"display current-configuration interface Vlanif{vid}" for vid in vlan_ids
            ]
            per_iface_commands.append("display current-configuration configuration dhcp")
            outputs = self._leer(per_iface_commands, device, password)
            config = "\n".join(outputs[:-1])
            svis = HuaweiSVIParser.parse_svis(
                config, brief,
                dhcp_groups=HuaweiSVIParser.parse_dhcp_relay_groups(outputs[-1]),
                dhcp_group_entries=HuaweiSVIParser.parse_dhcp_relay_group_entries(outputs[-1]),
            )

        return vlans, ports, svis

    def list_acl_names(self, device: Device, password: str) -> list[str]:
        commands = self._cargar_comandos()["list_acls"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        from app.services.parsers.svi_parser import parse_vrp_acl_names
        return parse_vrp_acl_names(stdouts[0] if stdouts else "")

    def list_acls(self, device: Device, password: str) -> list[dict]:
        commands = self._cargar_comandos()["list_acls"]["primary"]["commands"]
        stdouts = self._leer(commands, device, password)
        from app.services.parsers.svi_parser import parse_vrp_acls
        return parse_vrp_acls(stdouts[0] if stdouts else "")

    def _formatear_endpoint_acl(self, direction: str, endpoint: dict) -> "str | None":
        if endpoint.get("any"):
            return None
        if endpoint.get("host"):
            return f"{direction} {endpoint['host']} 0"
        network, wildcard = self._red_y_wildcard(endpoint["network"])
        return f"{direction} {network} {wildcard}"

    def formatear_regla_acl(self, rule: dict) -> str:
        partes = [rule["action"], rule["protocol"]]
        origen = self._formatear_endpoint_acl("source", rule["source"])
        if origen:
            partes.append(origen)
        destino = self._formatear_endpoint_acl("destination", rule["destination"])
        if destino:
            partes.append(destino)
        port = rule.get("port")
        if port:
            if port["operator"] == "range":
                partes.append(f"destination-port range {port['value']} {port['value2']}")
            else:
                partes.append(f"destination-port eq {port['value']}")
        return " ".join(partes)

    def create_or_update_acl(self, name: str, rule_lines: list[str], device: Device, password: str) -> dict:
        rule_lines = [f"rule {linea}" for linea in rule_lines]
        return self._aplicar_desde_template(
            "create_or_update_acl", {"name": name, "rule_lines": rule_lines}, device, password,
        )

    def remove_acl_rules(self, name: str, rule_lines: list[str], device: Device, password: str) -> dict:
        rule_lines = [f"rule {linea}" for linea in rule_lines]
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
        route_output = stdouts[2] if len(stdouts) > 2 else ""
        running_config = stdouts[3] if len(stdouts) > 3 else ""

        snmp_commands = self._cargar_comandos()["get_snmp_status"]["primary"]["commands"]
        try:
            self._leer(snmp_commands, device, password)
            snmp_enabled = True
        except RuntimeError as exc:
            if "snmp agent is not enabled" in str(exc).lower():
                snmp_enabled = False
            else:
                raise

        try:
            acls = self.list_acls(device, password)
        except RuntimeError:
            logger.exception("get_global_config: list_acls failed on device=%s, continuing without ACLs", device.name)
            acls = None

        from app.services.parsers.global_config_parser import HuaweiGlobalConfigParser
        config = HuaweiGlobalConfigParser.parse(
            version_output=version_output, hostname_output=hostname_output,
            route_output=route_output, running_config_output=running_config,
            snmp_enabled=snmp_enabled, acls=acls,
        )
        config.device = device.name
        config.acls = acls
        config.running_config = strip_known_preamble(running_config, _RUNNING_CONFIG_PREAMBLE) or None
        return config

    def set_hostname(self, hostname: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("set_hostname", {"hostname": hostname}, device, password)

    def set_snmp(self, cambios: dict, device: Device, password: str) -> dict:
        resultados = []
        if "version" in cambios:
            resultados.append(
                self._aplicar_desde_template("set_snmp_version", {"version": cambios["version"]}, device, password)
            )
        if "community" in cambios:
            resultados.append(
                self._aplicar_desde_template(
                    "set_snmp_community", {"verbo": "read", "community": cambios["community"]}, device, password,
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
                    {"host": cambios["trap_host"], "community": cambios["trap_host_community"]},
                    device, password,
                )
            )
        return self._combinar_resultados(resultados)

    def remove_snmp_trap_host(
        self, host: str, device: Device, password: str, *, community: "str | None" = None,
    ) -> dict:
        if not community:
            raise ValueError(
                "HuaweiVendor.remove_snmp_trap_host: 'community' is required -- VRP needs the exact "
                "community used when the trap host was added to match and remove it, and it can't be "
                "read back from the device (stored encrypted)"
            )
        return self._aplicar_desde_template(
            "remove_snmp_trap_host", {"host": host, "community": community}, device, password,
        )

    def add_log_server(self, server: str, level: "str | None", device: Device, password: str) -> dict:
        resultados = [self._aplicar_desde_template("add_log_host", {"server": server}, device, password)]
        if level:
            resultados.append(
                self._aplicar_desde_template("set_log_channel_level", {"level": level}, device, password)
            )
        return self._combinar_resultados(resultados)

    def remove_log_server(self, server: str, device: Device, password: str) -> dict:
        return self._aplicar_desde_template("remove_log_host", {"server": server}, device, password)

    def get_arp_table(self, device: Device, password: str) -> list[dict]:
        from app.services.parsers.arp_mac_parser import parse_huawei_arp

        raw = self._leer(["display arp"], device, password)[0]
        return parse_huawei_arp(raw)

    def get_mac_table(self, device: Device, password: str) -> list[dict]:
        from app.services.parsers.arp_mac_parser import parse_huawei_mac

        raw = self._leer(["display mac-address"], device, password)[0]
        return parse_huawei_mac(raw)

    def search_mac_table(self, pattern: str, device: Device, password: str) -> list[dict]:
        from app.services.parsers.arp_mac_parser import parse_huawei_mac

        raw = self._leer([f"display mac-address | include {pattern}"], device, password)[0]
        return parse_huawei_mac(raw)

    def get_log_buffer(self, device: Device, password: str) -> str:
        raw = self._leer(["display logbuffer"], device, password)[0]
        return raw.strip()

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
        if prefer:
            logger.info(
                "HuaweiVendor.add_ntp_server: 'prefer' has no confirmed VRP equivalent, "
                "ignoring for device=%s",
                device.name,
            )
        return self._aplicar_desde_template("add_ntp", {"server": server}, device, password)

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
