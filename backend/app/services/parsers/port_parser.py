from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.port import Puerto, PortMode
from app.services.parsers._common import strip_ansi

logger = logging.getLogger(__name__)


class PortParser(ABC):
    PSEUDO_PREFIXES: tuple[str, ...] = ()
    PHYSICAL_PREFIXES: tuple[str, ...] | None = None
    AGGREGATE_PREFIXES: tuple[str, ...] = ()

    @classmethod
    def clean(cls, lines: list[str]) -> list[str]:
        return [strip_ansi(ln).rstrip() for ln in lines]

    @classmethod
    def is_physical_port(cls, name: str) -> bool:
        if not name or name.startswith(cls.PSEUDO_PREFIXES):
            return False
        if cls.PHYSICAL_PREFIXES is None:
            return True
        return name.startswith(cls.PHYSICAL_PREFIXES)

    @classmethod
    def is_aggregate_port(cls, name: str) -> bool:
        return name.startswith(cls.AGGREGATE_PREFIXES)

    @classmethod
    @abstractmethod
    def parse_ports(cls, *raw_outputs: str) -> list[Puerto]:
        ...


class HuaweiPortParser(PortParser):
    PSEUDO_PREFIXES = (
        "Vlanif",
        "NULL",
        "LoopBack",
        "Tunnel",
        "Virtual-Template",
        "Cellular",
        "MEth",
        "Sip",
    )
    AGGREGATE_PREFIXES = ("Eth-Trunk",)

    @classmethod
    def parse_ports(
        cls,
        brief_output: str,
        description_output: str,
        port_vlan_output: str,
        storm_output: str = "",
    ) -> list[Puerto]:
        brief_rows = parse_vrp_interface_brief(brief_output) if brief_output else {}
        desc_rows = parse_vrp_interface_description(description_output) if description_output else {}
        vlan_rows = parse_vrp_port_vlan(port_vlan_output) if port_vlan_output else {}
        storm_rows = parse_vrp_storm_control(storm_output) if storm_output else {}

        names = set(brief_rows) | set(desc_rows) | set(vlan_rows)

        ports: list[Puerto] = []
        for name in sorted(names):
            brief = brief_rows.get(name)
            vlan = vlan_rows.get(name)
            description = desc_rows.get(name)
            storm = storm_rows.get(name)

            ports.append(
                Puerto(
                    interface=name,
                    kind="aggregate" if cls.is_aggregate_port(name) else "physical",
                    description=description,
                    admin_up=brief.admin_up if brief else None,
                    operational_up=brief.operational_up if brief else None,
                    mode=vlan.mode if vlan else "unknown",
                    access_vlan=vlan.access_vlan if vlan else None,
                    allowed_vlans=vlan.allowed_vlans if vlan else None,
                    storm_control_enabled=storm.enabled if storm else None,
                    storm_control_threshold=storm.threshold if storm else None,
                    storm_control_action=storm.action if storm else None,
                    storm_control_trap=storm.trap if storm else None,
                    poe_enabled=None,
                    speed=None,
                    duplex=None,
                )
            )

        logger.debug(
            "VRP port parser merged sources: brief=%d desc=%d portvlan=%d storm=%d → ports=%d",
            len(brief_rows), len(desc_rows), len(vlan_rows), len(storm_rows), len(ports),
        )
        return ports


_VRP_IFACE_ABBREV = (
    ("XGigabitEthernet", "XGE"),
    ("GigabitEthernet", "GE"),
)


def _normalizar_nombre_interfaz(name: str) -> str:
    for full, short in _VRP_IFACE_ABBREV:
        if name.startswith(full):
            return short + name[len(full):]
    return name


def expandir_nombre_interfaz(name: str) -> str:
    for full, short in _VRP_IFACE_ABBREV:
        if name.startswith(short) and not name.startswith(full):
            return full + name[len(short):]
    return name


@dataclass
class _BriefRow:
    name: str
    admin_up: bool | None
    operational_up: bool | None


def _parse_admin_state(phy_token: str) -> bool | None:
    if not phy_token:
        return None
    if phy_token.startswith("*"):
        return False
    return True


def _parse_operational_state(proto_token: str) -> bool | None:
    if not proto_token:
        return None
    head = proto_token.split("(", 1)[0].lower()
    return head == "up"


def parse_vrp_interface_brief(output: str) -> dict[str, _BriefRow]:
    rows: dict[str, _BriefRow] = {}
    in_table = False
    for line in HuaweiPortParser.clean(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if not in_table:
            if stripped.startswith("Interface") and "PHY" in stripped:
                in_table = True
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        name = _normalizar_nombre_interfaz(parts[0])
        if not HuaweiPortParser.is_physical_port(name):
            continue
        rows[name] = _BriefRow(
            name=name,
            admin_up=_parse_admin_state(parts[1]),
            operational_up=_parse_operational_state(parts[2]),
        )
    return rows


def parse_vrp_interface_description(output: str) -> dict[str, str | None]:
    descriptions: dict[str, str | None] = {}
    in_table = False
    header_columns: list[tuple[str, int]] = []

    for line in HuaweiPortParser.clean(output.splitlines()):
        if not in_table:
            stripped = line.strip()
            if stripped.startswith("Interface") and "Description" in stripped:
                in_table = True
                header_columns = _vrp_column_positions(line, ("Interface", "PHY", "Protocol", "Description"))
            continue

        if not line.strip():
            continue

        if len(header_columns) == 4:
            name = line[header_columns[0][1]:header_columns[1][1]].strip()
            desc = line[header_columns[3][1]:].strip()
        else:
            parts = line.strip().split(None, 3)
            if len(parts) < 3:
                continue
            name = parts[0]
            desc = parts[3].strip() if len(parts) == 4 else ""

        name = _normalizar_nombre_interfaz(name)
        if not name or not HuaweiPortParser.is_physical_port(name):
            continue
        descriptions[name] = desc or None
    return descriptions


def _vrp_column_positions(header_line: str, columns: tuple[str, ...]) -> list[tuple[str, int]]:
    positions: list[tuple[str, int]] = []
    cursor = 0
    for col in columns:
        idx = header_line.find(col, cursor)
        if idx == -1:
            return []
        positions.append((col, idx))
        cursor = idx + len(col)
    return positions


_VRP_TRUNK_VLAN_TOKEN_RE = re.compile(
    r"(\d+)\s+to\s+(\d+)|(\d+)-(\d+)|(\d+)",
    re.IGNORECASE,
)


def _parse_trunk_vlan_list_vrp(field_value: str) -> list[int] | None:
    cleaned = field_value.strip()
    if not cleaned or cleaned == "-":
        return None

    vlans: set[int] = set()
    for m in _VRP_TRUNK_VLAN_TOKEN_RE.finditer(cleaned):
        if m.group(1) is not None:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 1 <= lo <= hi <= 4094:
                vlans.update(range(lo, hi + 1))
        elif m.group(3) is not None:
            lo, hi = int(m.group(3)), int(m.group(4))
            if 1 <= lo <= hi <= 4094:
                vlans.update(range(lo, hi + 1))
        elif m.group(5) is not None:
            vid = int(m.group(5))
            if 1 <= vid <= 4094:
                vlans.add(vid)
    return sorted(vlans) if vlans else None


def _normalize_link_type(link_type: str) -> PortMode:
    token = link_type.lower()
    if token == "access":
        return "access"
    if token == "trunk":
        return "trunk"
    return "unknown"


@dataclass
class _PortVlanRow:
    name: str
    mode: PortMode
    access_vlan: int | None
    allowed_vlans: list[int] | None


def parse_vrp_port_vlan(output: str) -> dict[str, _PortVlanRow]:
    rows: dict[str, _PortVlanRow] = {}
    in_table = False
    header_columns: list[tuple[str, int]] = []
    last_name: str | None = None

    for raw_line in HuaweiPortParser.clean(output.splitlines()):
        if not in_table:
            stripped = raw_line.strip()
            if stripped.startswith("Port") and "Link Type" in stripped:
                in_table = True
                header_columns = _vrp_column_positions(
                    raw_line, ("Port", "Link Type", "PVID", "Trunk VLAN List", "Port Description")
                )
                if not header_columns:
                    header_columns = _vrp_column_positions(
                        raw_line, ("Port", "Link Type", "PVID", "Trunk VLAN List")
                    )
            continue

        stripped = raw_line.strip()
        if not stripped or stripped.startswith("-"):
            continue

        name = link_type = pvid_str = trunk_str = ""
        if len(header_columns) in (4, 5):
            trunk_end = header_columns[4][1] if len(header_columns) == 5 else len(raw_line)
            name = raw_line[header_columns[0][1]:header_columns[1][1]].strip()
            if not name:
                if last_name and last_name in rows:
                    cont_trunk_str = raw_line[header_columns[3][1]:trunk_end].strip()
                    additional = _parse_trunk_vlan_list_vrp(cont_trunk_str)
                    if additional is not None:
                        existing = rows[last_name].allowed_vlans or []
                        rows[last_name].allowed_vlans = sorted(set(existing) | set(additional)) or None
                continue
            link_type = raw_line[header_columns[1][1]:header_columns[2][1]].strip()
            pvid_str = raw_line[header_columns[2][1]:header_columns[3][1]].strip()
            trunk_str = raw_line[header_columns[3][1]:trunk_end].strip()
        else:
            parts = stripped.split(None, 3)
            if len(parts) >= 4:
                name, link_type, pvid_str, trunk_str = parts[0], parts[1], parts[2], parts[3]
            elif len(parts) == 3:
                name, link_type, pvid_str = parts[0], parts[1], parts[2]
            else:
                if last_name and last_name in rows:
                    additional = _parse_trunk_vlan_list_vrp(stripped)
                    if additional is not None:
                        existing = rows[last_name].allowed_vlans or []
                        merged = sorted(set(existing) | set(additional))
                        rows[last_name].allowed_vlans = merged or None
                continue

        name = _normalizar_nombre_interfaz(name)
        if not name or not HuaweiPortParser.is_physical_port(name):
            last_name = None
            continue

        mode = _normalize_link_type(link_type)
        try:
            access_vlan: int | None = int(pvid_str) if pvid_str.isdigit() else None
        except ValueError:
            access_vlan = None
        allowed = _parse_trunk_vlan_list_vrp(trunk_str) if trunk_str and mode == "trunk" else None

        rows[name] = _PortVlanRow(
            name=name,
            mode=mode,
            access_vlan=access_vlan,
            allowed_vlans=allowed,
        )
        last_name = name

    return rows


def parse_vrp_ports(brief_output: str, description_output: str, port_vlan_output: str) -> list[Puerto]:
    return HuaweiPortParser.parse_ports(brief_output, description_output, port_vlan_output)


@dataclass
class _StormRow:
    enabled: bool | None
    threshold: float | None
    action: str | None = None
    trap: bool | None = None


_STORM_LEVEL_PERCENT = re.compile(
    r"(?:percent|level)\s+(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*%"
)


def parse_vrp_storm_control(output: str) -> dict[str, _StormRow]:
    rows: dict[str, _StormRow] = {}
    current: str | None = None
    for line in HuaweiPortParser.clean(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("interface "):
            name = stripped.split(None, 1)[1].strip()
            name = _normalizar_nombre_interfaz(name)
            if HuaweiPortParser.is_physical_port(name):
                current = name
                rows.setdefault(current, _StormRow(enabled=False, threshold=None))
            else:
                current = None
            continue
        if current is None:
            continue
        if stripped == "#" or (line and not line.startswith(" ")):
            current = None
            continue
        if "storm control" in stripped or "storm-control" in stripped:
            existing = rows[current]
            threshold = existing.threshold
            action = existing.action
            trap = existing.trap
            match = _STORM_LEVEL_PERCENT.search(stripped)
            if match:
                threshold = float(match.group(1) or match.group(2))
            if "action" in stripped:
                if "shutdown" in stripped or "error-down" in stripped:
                    action = "shutdown"
                elif "block" in stripped:
                    action = "filter"
            if "enable trap" in stripped:
                trap = True
            rows[current] = _StormRow(enabled=True, threshold=threshold, action=action, trap=trap)
    for row in rows.values():
        if row.enabled:
            if row.action is None:
                row.action = "filter"
            if row.trap is None:
                row.trap = False
    return rows


_IOS_IFACE_ABBREV = (
    ("TwentyFiveGigE", "Tw"),
    ("TwoGigabitEthernet", "Tw"),
    ("TenGigabitEthernet", "Te"),
    ("HundredGigE", "Hu"),
    ("FortyGigabitEthernet", "Fo"),
    ("GigabitEthernet", "Gi"),
    ("FastEthernet", "Fa"),
    ("Port-channel", "Po"),
    ("Ethernet", "Et"),
)


def _abreviar_nombre_interfaz_ios(name: str) -> str:
    for full, short in _IOS_IFACE_ABBREV:
        if name.startswith(full):
            return short + name[len(full):]
    return name


def expandir_nombre_interfaz_ios(name: str) -> str:
    for full, short in _IOS_IFACE_ABBREV:
        if name.startswith(short) and not name.startswith(full):
            return full + name[len(short):]
    return name


_IOS_PORT_IFACE_HEADER = re.compile(r"^interface\s+(\S+)\s*$", re.IGNORECASE)
_IOS_STORM_ACTION = re.compile(r"^\s*storm-control\s+action\s+(shutdown|trap)\s*$", re.IGNORECASE)


def parse_ios_storm_control_actions(running_config_output: str) -> dict[str, tuple[str, bool]]:
    result: dict[str, tuple[str, bool]] = {}
    current: str | None = None
    action: str | None = None
    trap = False

    def _cerrar_actual() -> None:
        if current is not None and (action is not None or trap):
            result[current] = (action or "filter", trap)

    for raw in running_config_output.splitlines():
        line = strip_ansi(raw).rstrip()
        header = _IOS_PORT_IFACE_HEADER.match(line.strip())
        if header:
            _cerrar_actual()
            name = _abreviar_nombre_interfaz_ios(header.group(1))
            current = name if CiscoPortParser.is_physical_port(name) else None
            action = None
            trap = False
            continue
        if current is None:
            continue
        m = _IOS_STORM_ACTION.match(line)
        if m:
            verb = m.group(1).lower()
            if verb == "shutdown":
                action = "shutdown"
            else:
                trap = True
            continue
    _cerrar_actual()
    return result


def parse_ios_storm_control_from_config(running_config_output: str) -> dict[str, _StormRow]:
    rows: dict[str, _StormRow] = {}
    current: str | None = None
    for raw in running_config_output.splitlines():
        line = strip_ansi(raw).rstrip()
        header = _IOS_PORT_IFACE_HEADER.match(line.strip())
        if header:
            name = _abreviar_nombre_interfaz_ios(header.group(1))
            current = name if CiscoPortParser.is_physical_port(name) else None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped.startswith("storm-control"):
            continue
        existing = rows.get(current, _StormRow(enabled=True, threshold=None))
        m = _STORM_LEVEL_PERCENT.search(stripped)
        if m and existing.threshold is None:
            existing = _StormRow(enabled=True, threshold=float(m.group(1) or m.group(2)))
        rows[current] = existing
    return rows


class CiscoPortParser(PortParser):
    PHYSICAL_PREFIXES = (
        "Gi",
        "Fa",
        "Te",
        "Tw",
        "Fo",
        "Hu",
        "Et",
        "Po",
    )

    PSEUDO_PREFIXES = (
        "Vl",
        "Lo",
        "Tu",
        "Nu",
        "Mg",
        "BV",
        "VL",
    )

    AGGREGATE_PREFIXES = ("Po",)

    @classmethod
    def parse_ports(
        cls,
        status_output: str,
        description_output: str,
        switchport_output: str,
        storm_output: str = "",
        running_config_output: str = "",
    ) -> list[Puerto]:
        status_rows = parse_ios_interface_status(status_output) if status_output else {}
        desc_rows = parse_ios_interface_description(description_output) if description_output else {}
        sw_rows = parse_ios_switchport(switchport_output) if switchport_output else {}
        storm_rows = parse_ios_storm_control(storm_output) if storm_output else {}
        storm_actions = (
            parse_ios_storm_control_actions(running_config_output) if running_config_output else {}
        )
        storm_config_rows = (
            parse_ios_storm_control_from_config(running_config_output) if running_config_output else {}
        )

        ports: list[Puerto] = []
        for name in sorted(sw_rows.keys()):
            sw = sw_rows[name]
            desc = desc_rows.get(name)
            status = status_rows.get(name)
            storm = storm_rows.get(name)

            if desc is not None:
                admin_up = desc.admin_up
                operational_up = desc.operational_up
                description = desc.description
            elif status is not None:
                admin_up = status.admin_up
                operational_up = status.operational_up
                description = None
            else:
                admin_up = None
                operational_up = None
                description = None

            action, trap = storm_actions.get(name, (None, None))

            storm_cfg = storm_config_rows.get(name)
            if storm is not None and storm.enabled is not None:
                storm_enabled, storm_threshold = storm.enabled, storm.threshold
            elif storm_cfg is not None:
                storm_enabled, storm_threshold = storm_cfg.enabled, storm_cfg.threshold
            elif storm_output:
                storm_enabled, storm_threshold = False, None
            else:
                storm_enabled, storm_threshold = None, None

            if storm_enabled and action is None:
                action = "filter"
                trap = False

            ports.append(
                Puerto(
                    interface=name,
                    kind="aggregate" if cls.is_aggregate_port(name) else "physical",
                    description=description,
                    admin_up=admin_up,
                    operational_up=operational_up,
                    mode=sw.mode,
                    access_vlan=sw.access_vlan,
                    allowed_vlans=sw.allowed_vlans,
                    storm_control_enabled=storm_enabled,
                    storm_control_threshold=storm_threshold,
                    storm_control_action=action,
                    storm_control_trap=trap,
                    poe_enabled=None,
                    speed=None,
                    duplex=None,
                )
            )

        logger.debug(
            "IOS port parser merged sources: status=%d desc=%d switchport=%d storm=%d → ports=%d",
            len(status_rows), len(desc_rows), len(sw_rows), len(storm_rows), len(ports),
        )
        return ports


@dataclass
class _StatusRow:
    name: str
    status: str
    vlan_token: str
    admin_up: bool | None
    operational_up: bool | None


_STATUS_TO_STATE: dict[str, tuple[bool | None, bool | None]] = {
    "connected":              (True,  True),
    "notconnect":             (True,  False),
    "noconnect":              (True,  False),
    "disabled":               (False, False),
    "err-disabled":           (True,  False),
    "errdisabled":            (True,  False),
    "monitoring":             (True,  True),
    "suspended":              (True,  False),
    "inactive":               (True,  False),
    "down":                   (True,  False),
    "up":                     (True,  True),
}


def parse_ios_interface_status(output: str) -> dict[str, _StatusRow]:
    rows: dict[str, _StatusRow] = {}
    in_table = False
    name_start = status_start = vlan_start = duplex_start = -1

    for line in CiscoPortParser.clean(output.splitlines()):
        if not in_table:
            stripped = line.strip()
            if stripped.startswith("Port") and "Status" in stripped and "Vlan" in stripped:
                in_table = True
                name_start = line.find("Name")
                status_start = line.find("Status")
                vlan_start = line.find("Vlan")
                duplex_start = line.find("Duplex")
            continue

        if not line.strip():
            continue
        if not line[:1].isalpha():
            continue

        if min(name_start, status_start, vlan_start, duplex_start) < 0:
            parts = line.split()
            if len(parts) < 3:
                continue
            name = parts[0]
            status = parts[-4] if len(parts) >= 5 else parts[-3] if len(parts) >= 4 else parts[-2]
            vlan_token = ""
            for i, tok in enumerate(parts):
                if tok.lower() in _STATUS_TO_STATE:
                    status = tok
                    vlan_token = parts[i + 1] if i + 1 < len(parts) else ""
                    break
        else:
            name = line[:name_start].strip()
            status = line[status_start:vlan_start].strip()
            vlan_token = line[vlan_start:duplex_start].strip()

        if not CiscoPortParser.is_physical_port(name):
            continue

        admin_up, oper_up = _STATUS_TO_STATE.get(status.lower(), (None, None))
        rows[name] = _StatusRow(
            name=name,
            status=status,
            vlan_token=vlan_token,
            admin_up=admin_up,
            operational_up=oper_up,
        )
    return rows


@dataclass
class _DescriptionRow:
    name: str
    admin_up: bool | None
    operational_up: bool | None
    description: str | None


def parse_ios_interface_description(output: str) -> dict[str, _DescriptionRow]:
    rows: dict[str, _DescriptionRow] = {}
    in_table = False
    iface_start = status_start = protocol_start = description_start = -1

    for line in CiscoPortParser.clean(output.splitlines()):
        if not in_table:
            stripped = line.strip()
            if (
                stripped.startswith("Interface")
                and "Status" in stripped
                and "Protocol" in stripped
                and "Description" in stripped
            ):
                in_table = True
                iface_start = line.find("Interface")
                status_start = line.find("Status")
                protocol_start = line.find("Protocol")
                description_start = line.find("Description")
            continue

        if not line.strip():
            continue
        if not line[:1].isalpha():
            continue

        if (
            iface_start >= 0
            and status_start > iface_start
            and protocol_start > status_start
            and description_start > protocol_start
        ):
            name = line[iface_start:status_start].strip()
            status_tok = line[status_start:protocol_start].strip()
            proto_tok = line[protocol_start:description_start].strip()
            desc = line[description_start:].rstrip()
        else:
            parts = line.split(None, 4)
            if len(parts) < 3:
                continue
            name = parts[0]
            if len(parts) >= 4 and parts[1].lower() == "admin" and parts[2].lower() == "down":
                status_tok = "admin down"
                proto_tok = parts[3] if len(parts) > 3 else ""
                desc = parts[4].strip() if len(parts) > 4 else ""
            else:
                status_tok = parts[1]
                proto_tok = parts[2] if len(parts) > 2 else ""
                desc = " ".join(parts[3:]).strip() if len(parts) > 3 else ""

        if not CiscoPortParser.is_physical_port(name):
            continue

        admin_up = _parse_description_admin(status_tok)
        oper_up = _parse_description_protocol(proto_tok)

        rows[name] = _DescriptionRow(
            name=name,
            admin_up=admin_up,
            operational_up=oper_up,
            description=desc.strip() or None,
        )
    return rows


def _parse_description_admin(status_token: str) -> bool | None:
    if not status_token:
        return None
    token = status_token.strip().lower()
    if token.startswith("admin"):
        return False
    return True


def _parse_description_protocol(protocol_token: str) -> bool | None:
    if not protocol_token:
        return None
    head = protocol_token.strip().lower().split()[0]
    return head == "up"


@dataclass
class _SwitchportRow:
    name: str
    switchport_enabled: bool
    mode: PortMode
    access_vlan: int | None
    allowed_vlans: list[int] | None


_IOS_RANGE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_IOS_NAME_LINE_RE = re.compile(r"^\s*Name\s*:\s*(\S+)")
_IOS_VLAN_WITH_LABEL_RE = re.compile(r"^\s*(\d+)\b")


def _normalize_mode(mode_token: str) -> PortMode:
    token = mode_token.strip().lower()
    if not token:
        return "unknown"
    if "trunk" in token:
        return "trunk"
    if "access" in token:
        return "access"
    return "unknown"


def _parse_vlan_id_with_label(value: str) -> int | None:
    m = _IOS_VLAN_WITH_LABEL_RE.match(value or "")
    if not m:
        return None
    try:
        vid = int(m.group(1))
    except ValueError:
        return None
    return vid if 1 <= vid <= 4094 else None


def _parse_trunk_vlan_list_ios(value: str) -> list[int] | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper == "ALL":
        return list(range(1, 4095))
    if upper == "NONE":
        return []

    vlans: set[int] = set()
    for token in cleaned.split(","):
        tok = token.strip()
        if not tok:
            continue
        m = _IOS_RANGE_RE.match(tok)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 1 <= lo <= hi <= 4094:
                vlans.update(range(lo, hi + 1))
            continue
        if tok.isdigit():
            vid = int(tok)
            if 1 <= vid <= 4094:
                vlans.add(vid)
            continue
        m2 = _IOS_VLAN_WITH_LABEL_RE.match(tok)
        if m2:
            try:
                vid = int(m2.group(1))
            except ValueError:
                continue
            if 1 <= vid <= 4094:
                vlans.add(vid)
    return sorted(vlans) if vlans else None


def _split_switchport_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    started = False
    for line in lines:
        if _IOS_NAME_LINE_RE.match(line):
            if started:
                blocks.append(current)
            current = [line]
            started = True
        elif started:
            current.append(line)
    if started:
        blocks.append(current)
    return blocks


def _extract_field(block: list[str], key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*)$")
    other_key = re.compile(r"^\s*[A-Z][\w\-/ ]*\s*:\s")
    value_parts: list[str] = []
    started = False

    for line in block:
        if not started:
            m = pattern.match(line)
            if m:
                value_parts.append(m.group(1).strip())
                started = True
            continue

        if other_key.match(line):
            break
        stripped = line.strip()
        if not stripped:
            break
        value_parts.append(stripped)

    if not value_parts:
        return None
    joined = ",".join(p.rstrip(",") for p in value_parts)
    return joined.strip() or None


def parse_ios_switchport(output: str) -> dict[str, _SwitchportRow]:
    rows: dict[str, _SwitchportRow] = {}
    lines = CiscoPortParser.clean(output.splitlines())
    for block in _split_switchport_blocks(lines):
        name_match = _IOS_NAME_LINE_RE.match(block[0])
        if not name_match:
            continue
        name = name_match.group(1)
        if not CiscoPortParser.is_physical_port(name):
            continue

        sw_enabled_raw = _extract_field(block, "Switchport")
        switchport_enabled = (sw_enabled_raw or "").lower().startswith("enab")
        if not switchport_enabled:
            continue

        op_mode = _extract_field(block, "Operational Mode") or ""
        admin_mode = _extract_field(block, "Administrative Mode") or ""
        mode = _normalize_mode(op_mode)
        if mode == "unknown":
            mode = _normalize_mode(admin_mode)

        access_vlan_raw = _extract_field(block, "Access Mode VLAN")
        native_vlan_raw = _extract_field(block, "Trunking Native Mode VLAN")
        allowed_raw = _extract_field(block, "Trunking VLANs Enabled")

        if mode == "trunk":
            access_vlan = _parse_vlan_id_with_label(native_vlan_raw or "")
            allowed_vlans = _parse_trunk_vlan_list_ios(allowed_raw or "")
        else:
            access_vlan = _parse_vlan_id_with_label(access_vlan_raw or "")
            allowed_vlans = None

        rows[name] = _SwitchportRow(
            name=name,
            switchport_enabled=switchport_enabled,
            mode=mode,
            access_vlan=access_vlan,
            allowed_vlans=allowed_vlans,
        )
    return rows


def parse_ios_ports(status_output: str, description_output: str, switchport_output: str) -> list[Puerto]:
    return CiscoPortParser.parse_ports(status_output, description_output, switchport_output)


def parse_ios_storm_control(output: str) -> dict[str, _StormRow]:
    rows: dict[str, _StormRow] = {}
    in_table = False
    for line in CiscoPortParser.clean(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if not in_table:
            if stripped.startswith("Interface") and "Filter" in stripped:
                in_table = True
            continue
        if stripped.startswith("---"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        name = parts[0]
        if not CiscoPortParser.is_physical_port(name):
            continue
        state_lower = parts[1].lower()
        if state_lower in ("forwarding", "blocking"):
            enabled: bool | None = True
            rest = parts[2:]
        elif state_lower == "inactive":
            enabled = False
            rest = parts[2:]
        elif state_lower == "link" and len(parts) > 2 and parts[2].lower() == "down":
            enabled = None
            rest = parts[3:]
        else:
            continue
        threshold: float | None = None
        for token in rest:
            m = _STORM_LEVEL_PERCENT.search(token)
            if m:
                threshold = float(m.group(1) or m.group(2))
                break
        rows[name] = _StormRow(enabled=enabled, threshold=threshold)
    return rows


_PARSERS_BY_VENDOR: dict[str, type[PortParser]] = {
    "huawei_vrp": HuaweiPortParser,
    "cisco_ios": CiscoPortParser,
}


def is_aggregate_interface(vendor: str, interface: str) -> bool:
    parser = _PARSERS_BY_VENDOR.get(vendor)
    return bool(parser and parser.is_aggregate_port(interface))
