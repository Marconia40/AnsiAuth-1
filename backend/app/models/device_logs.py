from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceLogs:
    device: str = ""
    log_output: str | None = None
