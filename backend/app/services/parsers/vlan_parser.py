from __future__ import annotations

import re

from app.models.vlan import VLAN
from app.services.parsers._common import strip_ansi

_IOS_INTERNAL = {1, 1002, 1003, 1004, 1005}

_VRP_INTERNAL = {1}

_VRP_DETAIL_HEADER = re.compile(r"^VID\s+(?:Type\s+)?Status\s+Property", re.IGNORECASE)

_VRP_VLAN_BLOCK = re.compile(r"(?:The information of )?VLAN\s+(\d+)\s*:", re.IGNORECASE)
_VRP_NAME_LINE = re.compile(r"VLAN\s+Name\s*:\s*(.+)", re.IGNORECASE)


def parse_vrp_vlan_display(output: str) -> list[VLAN]:
    clean_lines = [strip_ansi(line) for line in output.splitlines()]

    detail_start = next(
        (i for i, line in enumerate(clean_lines) if _VRP_DETAIL_HEADER.match(line.strip())),
        None,
    )
    if detail_start is not None:
        header_cols = clean_lines[detail_start].strip().split()
        num_fixed_cols = max(len(header_cols) - 1, 1)
        return _parse_vrp_tabular(clean_lines[detail_start + 1:], num_fixed_cols)

    return _parse_vrp_block(clean_lines)


def _parse_vrp_tabular(lines: list[str], num_fixed_cols: int) -> list[VLAN]:
    vlans: list[VLAN] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("-"):
            continue
        parts = line.split()
        if not parts[0].isdigit():
            continue
        vlan_id = int(parts[0])
        if vlan_id in _VRP_INTERNAL:
            continue
        description = " ".join(parts[num_fixed_cols:]).strip() if len(parts) > num_fixed_cols else ""
        vlans.append(VLAN(
            vlan_id=vlan_id,
            name=description or f"VLAN{vlan_id:04d}",
        ))
    return vlans


def _parse_vrp_block(lines: list[str]) -> list[VLAN]:
    vlans: list[VLAN] = []
    current_id: int | None = None
    current_name: str | None = None

    for line in lines:
        line = line.strip()
        block_match = _VRP_VLAN_BLOCK.match(line)
        if block_match:
            if current_id is not None and current_id not in _VRP_INTERNAL:
                vlans.append(VLAN(
                    vlan_id=current_id,
                    name=current_name or f"VLAN{current_id:04d}",
                ))
            current_id = int(block_match.group(1))
            current_name = None
            continue
        if current_id is not None:
            name_match = _VRP_NAME_LINE.match(line)
            if name_match:
                current_name = name_match.group(1).strip().rstrip(".")

    if current_id is not None and current_id not in _VRP_INTERNAL:
        vlans.append(VLAN(
            vlan_id=current_id,
            name=current_name or f"VLAN{current_id:04d}",
        ))

    return vlans


def parse_vlan_brief(output: str) -> list[VLAN]:
    vlans: list[VLAN] = []
    for line in output.splitlines():
        line = strip_ansi(line)
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            vlan_id = int(parts[0])
            if vlan_id not in _IOS_INTERNAL:
                vlans.append(VLAN(vlan_id=vlan_id, name=parts[1]))
    return vlans
