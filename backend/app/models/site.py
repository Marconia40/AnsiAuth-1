from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

SiteKind = Literal["REGULAR", "BASE_INFRASTRUCTURE"]


@dataclass
class Site:
    id: int
    name: str
    description: Optional[str] = None
    kind: SiteKind = "REGULAR"
    default_group_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def renombrar(self, nuevo_nombre: str) -> None:
        self.name = nuevo_nombre

    def actualizar_descripcion(self, desc: str) -> None:
        self.description = desc

    def es_base_infraestructura(self) -> bool:
        return self.kind == "BASE_INFRASTRUCTURE"
