from datetime import datetime, timezone
from typing import Callable, Optional

from app.core.repository import Repository
from app.db.models import JobModel
from app.db.session import get_session
from app.models.job import Job
from app.models.visibility_scope import VisibilityScope


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_domain(row: JobModel) -> Job:
    return Job(
        job_id=row.job_id,
        status=row.status,
        operation=row.operation,
        playbook=row.playbook,
        device=row.device,
        parameters=row.parameters,
        parameters_summary=row.parameters_summary,
        result=row.result,
        error=row.error,
        created_at=_ensure_utc(row.created_at),
        started_at=_ensure_utc(row.started_at),
        finished_at=_ensure_utc(row.finished_at),
        retry_count=row.retry_count,
        max_retries=row.max_retries,
        rollback_performed=row.rollback_performed,
        rollback_success=row.rollback_success,
        pre_state=row.pre_state,
        last_error=row.last_error,
        error_type=row.error_type,
        error_reason=row.error_reason,
        error_summary=row.error_summary,
        rollback_error=row.rollback_error,
        current_step=row.current_step,
        group_job_id=row.group_job_id,
    )


def _to_orm(j: Job) -> JobModel:
    return JobModel(
        job_id=j.job_id, status=j.status, operation=j.operation, playbook=j.playbook,
        device=j.device, parameters=j.parameters, parameters_summary=j.parameters_summary,
        result=j.result, error=j.error,
        created_at=j.created_at, started_at=j.started_at, finished_at=j.finished_at,
        retry_count=j.retry_count, max_retries=j.max_retries,
        rollback_performed=j.rollback_performed, rollback_success=j.rollback_success,
        pre_state=j.pre_state, last_error=j.last_error,
        error_type=j.error_type, error_reason=j.error_reason, error_summary=j.error_summary,
        rollback_error=j.rollback_error,
        current_step=j.current_step,
        group_job_id=j.group_job_id,
    )


class JobRepository(Repository):
    def __init__(self):
        super().__init__(JobModel, _to_domain, _to_orm, pk_field="job_id")

    def activo_para(self, device: str) -> bool:
        with get_session() as session:
            existe = (
                session.query(JobModel)
                .filter(JobModel.device == device, JobModel.status.in_(("pending", "running")))
                .first()
            )
            return existe is not None

    def hay_otros_activos(self, device: str, operation: str, excluir_job_id: str) -> bool:
        with get_session() as session:
            existe = (
                session.query(JobModel)
                .filter(
                    JobModel.device == device,
                    JobModel.operation == operation,
                    JobModel.status.in_(("pending", "running")),
                    JobModel.job_id != excluir_job_id,
                )
                .first()
            )
            return existe is not None

    def cancelar_si_pendiente(self, job: Job) -> bool:
        job.cancelar()
        with get_session() as session:
            filas = (
                session.query(JobModel)
                .filter(JobModel.job_id == job.job_id, JobModel.status == "pending")
                .update({"status": job.status, "finished_at": job.finished_at},
                        synchronize_session=False)
            )
        return filas == 1

    def iniciar_si_pendiente(self, job: Job) -> bool:
        job.marcar_iniciado()
        with get_session() as session:
            filas = (
                session.query(JobModel)
                .filter(JobModel.job_id == job.job_id, JobModel.status == "pending")
                .update({"status": job.status, "started_at": job.started_at,
                         "current_step": job.current_step},
                        synchronize_session=False)
            )
        return filas == 1

    def recuperar_huerfanos(self, es_huerfano: "Callable[[Job], bool] | None" = None) -> int:
        with get_session() as session:
            filas = session.query(JobModel).filter(JobModel.status == "running").all()
            n = 0
            for row in filas:
                job = _to_domain(row)
                if es_huerfano is not None and not es_huerfano(job):
                    continue
                job.asegurar_estado_final()
                row.status = job.status
                row.error = job.error
                row.finished_at = job.finished_at
                n += 1
            return n

    def list_retry_rollbacks(self, original_job_id: str, limit: int = 10) -> list[Job]:
        with get_session() as session:
            rows = (
                session.query(JobModel)
                .filter(JobModel.operation == "retry_rollback")
                .order_by(JobModel.created_at.desc())
                .limit(200)
                .all()
            )
            matches = [
                _to_domain(row) for row in rows
                if row.parameters and row.parameters.get("retry_of_job_id") == original_job_id
            ]
            return matches[:limit]

    def resumen_de_grupo(
        self, group_job_id: str, scope: "VisibilityScope | None" = None,
    ) -> "dict | None":
        jobs = self.list(group_job_id=group_job_id)
        if scope is not None and not scope.es_system_admin:
            from app.composition import device_repository

            nombres = device_repository.nombres_visibles(scope)
            if nombres is not None:
                jobs = [j for j in jobs if j.device in nombres]
        if not jobs:
            return None
        completed = sum(1 for j in jobs if j.status == "completed")
        failed = sum(1 for j in jobs if j.status == "failed")
        cancelled = sum(1 for j in jobs if j.status == "cancelled")
        rollback_count = sum(1 for j in jobs if j.rollback_performed)
        estados = {j.status for j in jobs}
        todos_terminales = all(j.esta_en_estado_terminal() for j in jobs)
        if estados <= {"pending"}:
            status_grupo = "pending"
        elif not todos_terminales:
            status_grupo = "running"
        elif cancelled == len(jobs):
            status_grupo = "cancelled"
        elif completed == len(jobs):
            status_grupo = "completed"
        elif completed == 0:
            status_grupo = "failed"
        else:
            status_grupo = "partial_success"
        primero = jobs[0]
        started = [j.started_at for j in jobs if j.started_at]
        finished = [j.finished_at for j in jobs if j.finished_at]
        duration_ms_grupo = (
            round((max(finished) - min(started)).total_seconds() * 1000)
            if started and finished and todos_terminales else None
        )

        def _duration_ms(j: "Job") -> "int | None":
            if j.started_at and j.finished_at:
                return round((j.finished_at - j.started_at).total_seconds() * 1000)
            return None

        return {
            "group_job_id": group_job_id,
            "status": status_grupo,
            "operation": primero.operation,
            "playbook": primero.playbook,
            "parameters": primero.parameters,
            "parameters_summary": primero.parameters_summary,
            "created_at": min((j.created_at for j in jobs), default=None),
            "started_at": min(started, default=None),
            "finished_at": max(finished, default=None) if todos_terminales else None,
            "execution_summary": {
                "total_devices": len(jobs),
                "completed": completed,
                "failed": failed,
                "cancelled": cancelled,
                "partial_success": completed > 0 and completed < len(jobs) and todos_terminales,
                "rollback_count": rollback_count,
                "duration_ms": duration_ms_grupo,
            },
            "device_results": [
                {
                    "device": j.device, "job_id": j.job_id, "status": j.status,
                    "current_step": j.current_step, "retry_count": j.retry_count,
                    "rollback_performed": j.rollback_performed,
                    "rollback_success": j.rollback_success, "error": j.error,
                    "error_type": j.error_type,
                    "error_reason": j.error_reason,
                    "error_summary": j.error_summary,
                    "rollback_error": j.rollback_error,
                    "duration_ms": _duration_ms(j),
                }
                for j in jobs
            ],
        }

    def query(
        self,
        *,
        status: Optional[str] = None,
        device: Optional[str] = None,
        site_id: Optional[int] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        scope: VisibilityScope,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Job], int]:
        from app.composition import device_repository

        with get_session() as session:
            q = session.query(JobModel)
            if status is not None:
                q = q.filter(JobModel.status == status)
            if device is not None:
                q = q.filter(JobModel.device == device)
            if from_date is not None:
                q = q.filter(JobModel.created_at >= from_date)
            if to_date is not None:
                q = q.filter(JobModel.created_at <= to_date)
            if site_id is not None:
                from app.db.models import DeviceGroupModel, DeviceModel
                nombres_site = [
                    r[0]
                    for r in session.query(DeviceModel.name)
                    .join(DeviceGroupModel, DeviceModel.device_group_id == DeviceGroupModel.id)
                    .filter(DeviceGroupModel.site_id == site_id)
                    .all()
                ]
                if not nombres_site:
                    return [], 0
                q = q.filter(JobModel.device.in_(nombres_site))
            if not scope.es_system_admin:
                nombres = device_repository.nombres_visibles(scope)
                if nombres is not None:
                    if not nombres:
                        return [], 0
                    q = q.filter(JobModel.device.in_(nombres))
            total = q.count()
            rows = (
                q.order_by(JobModel.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return [_to_domain(r) for r in rows], total
