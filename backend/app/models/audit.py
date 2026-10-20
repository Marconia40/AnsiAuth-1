import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class AuditRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user: str
    action: str
    resource: str
    resource_id: Optional[str] = None
    details: dict
    status: str = "success"
    job_id: Optional[str] = None
    device: Optional[str] = None
    request_id: Optional[str] = None
    parent_audit_id: Optional[str] = None
    summary: Optional[str] = None

    @staticmethod
    def _resumir(evento: "DomainEvent") -> "str | None":
        recurso = evento.recurso
        resumen_lote = evento.payload.get("resumen_lote")
        if resumen_lote:
            intento = resumen_lote
        elif hasattr(recurso, "resumen_intento"):
            intento = recurso.resumen_intento()
        else:
            return None
        if not evento.exitoso:
            razon = evento.payload.get("error_summary")
            return f"{intento} — failed: {razon}" if razon else f"{intento} — failed"
        if evento.payload.get("noop"):
            return f"{intento} (no changes needed)"
        return intento

    @classmethod
    def desde(cls, evento: "DomainEvent") -> "AuditRecord":
        accion = evento.payload.get("accion", evento.tipo)
        resource_id = evento.payload.get("resource_id")
        return cls(
            timestamp=datetime.now(timezone.utc),
            user=evento.actor,
            action=accion,
            resource=evento.recurso.repositorio() if hasattr(evento.recurso, "repositorio") else type(evento.recurso).__name__.lower(),
            resource_id=str(resource_id) if resource_id is not None else None,
            details=evento.payload,
            summary=cls._resumir(evento),
            status="success" if evento.exitoso else "failure",
            device=getattr(evento.device, "name", None),
        )
