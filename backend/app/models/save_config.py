from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from app.models.device import Device


@dataclass
class GuardarConfig:
    device: str = ""

    PERSISTE_EN_CACHE: ClassVar[bool] = False

    def validar(self) -> None:
        return None

    def reconciliar(self, device: "Device") -> dict:
        return {"existed": True, "actual": None}

    def resolver_paso(self, device: "Device", actual: "object | None") -> "tuple[str, str | None, dict]":
        return "save_config", None, {}

    def aplicar(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        resultado = device.driver.save_config(device, device.password)
        return {**resultado, "accion": "guardar_configuracion"}

    def ejecutar_rollback(self, pre_state: dict, device: "Device") -> "tuple[bool, bool | None]":
        return False, None

    def repositorio(self) -> str:
        return "save_config"

    def resumen_intento(self) -> str:
        return f"Save the running configuration of {self.device}" if self.device else "Save the running configuration"
