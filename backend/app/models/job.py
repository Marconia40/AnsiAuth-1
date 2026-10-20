import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.exceptions import TransicionInvalidaError

_TRANSICIONES_VALIDAS: dict[str, set[str]] = {
    "pending":   {"running", "cancelled"},
    "running":   {"completed", "failed"},
    "completed": set(),
    "failed":    set(),
    "cancelled": set(),
}

_LIMITE_ERROR = 4000
_LIMITE_LAST_ERROR = 500
_SUFIJO_TRUNCADO = "... [truncated]"


def _truncar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[: limite - len(_SUFIJO_TRUNCADO)] + _SUFIJO_TRUNCADO


@dataclass
class Job:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    operation: Optional[str] = None
    playbook: Optional[str] = None
    device: Optional[str] = None
    parameters: Optional[dict] = None
    parameters_summary: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    rollback_performed: bool = False
    rollback_success: Optional[bool] = None
    pre_state: Optional[dict] = None
    last_error: Optional[str] = None
    error_type: Optional[str] = None
    error_reason: Optional[str] = None
    error_summary: Optional[str] = None
    rollback_error: Optional[str] = None
    current_step: Optional[str] = None
    group_job_id: Optional[str] = None

    def _transicionar(self, nuevo_status: str) -> None:
        validas = _TRANSICIONES_VALIDAS.get(self.status, set())
        if nuevo_status not in validas:
            raise TransicionInvalidaError(
                f"Job {self.job_id}: transición inválida {self.status!r} -> {nuevo_status!r}"
            )
        self.status = nuevo_status

    def esta_en_estado_terminal(self) -> bool:
        return not _TRANSICIONES_VALIDAS.get(self.status, {"__nunca__"})

    def marcar_iniciado(self) -> None:
        self._transicionar("running")
        self.started_at = datetime.now(timezone.utc)
        self.current_step = "executing"

    def marcar_completado(self, resultado: dict) -> None:
        self._transicionar("completed")
        self.result = resultado
        self.finished_at = datetime.now(timezone.utc)
        self.current_step = "completed"

    def marcar_fallido(
        self,
        error: str,
        rollback_performed: bool = False,
        rollback_success: Optional[bool] = None,
        error_type: Optional[str] = None,
        error_reason: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> None:
        self._transicionar("failed")
        self.error = _truncar(error, _LIMITE_ERROR)
        self.rollback_performed = rollback_performed
        self.rollback_success = rollback_success
        self.error_type = error_type
        self.error_reason = error_reason
        self.error_summary = error_summary
        self.finished_at = datetime.now(timezone.utc)
        self.current_step = "failed"

    def cancelar(self) -> None:
        self._transicionar("cancelled")
        self.finished_at = datetime.now(timezone.utc)

    def registrar_reintento(self, error: str) -> None:
        self.retry_count += 1
        self.last_error = _truncar(error.strip(), _LIMITE_LAST_ERROR)
        self.current_step = "retrying"

    def asegurar_estado_final(self) -> None:
        if not self.esta_en_estado_terminal():
            self.status = "failed"
            if not self.error:
                self.error = "Unexpected termination"
            self.finished_at = datetime.now(timezone.utc)
