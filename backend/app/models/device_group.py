from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.core.exceptions import DefaultGroupImmutableError


@dataclass
class DeviceGroup:
    id: int
    name: str
    description: Optional[str] = None
    site_id: Optional[int] = None
    es_default: bool = False
    created_at: Optional[datetime] = None

    def repositorio(self) -> str:
        return "device_group"

    def renombrar(self, nuevo_nombre: str) -> None:
        if self.es_default:
            raise DefaultGroupImmutableError(
                f"El grupo {self.id} es el Default del site y no se puede renombrar (D7)"
            )
        self.name = nuevo_nombre
