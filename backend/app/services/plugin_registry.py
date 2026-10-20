from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.vendors.base import VendorDriver


class PluginRegistry:
    def __init__(self):
        self._vendors: dict[str, "VendorDriver"] = {}

    def registrar(self, vendor: str, driver: "VendorDriver") -> None:
        self._vendors[vendor] = driver

    def obtener(self, vendor: str) -> "VendorDriver":
        if vendor not in self._vendors:
            raise ValueError(f"No hay driver registrado para vendor='{vendor}'")
        return self._vendors[vendor]
