from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArpMacTables:
    device: str = ""
    arp_table: list[dict] | None = None
    mac_table: list[dict] | None = None
