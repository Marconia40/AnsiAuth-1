import uuid
from dataclasses import asdict

from app.models.job import Job


class GroupOperationRunner:
    def __init__(self, orquestador, job_queue, jobs):
        self._orquestador = orquestador
        self._job_queue = job_queue
        self._jobs = jobs

    def encolar(self, recurso: "RecursoGestionable", devices: list[str], actor: str) -> tuple[str, list[dict]]:
        group_job_id = str(uuid.uuid4())
        parametros = asdict(recurso)
        resumen = recurso.resumen_intento()
        job_entries = []
        for device_name in devices:
            job = Job(
                operation=recurso.repositorio(), device=device_name,
                group_job_id=group_job_id, parameters=parametros,
                parameters_summary=resumen,
            )
            self._jobs.add(job)
            self._job_queue.dispatch(recurso, device_name, actor, job.job_id)
            job_entries.append({"device": device_name, "job_id": job.job_id, "status": job.status})
        return group_job_id, job_entries

    def encolar_lote(
        self, recursos: "list[RecursoGestionable]", device_name: str, actor: str,
        *, group_job_id: "str | None" = None,
    ) -> tuple[str, dict]:
        if group_job_id is None:
            group_job_id = str(uuid.uuid4())
        parametros = {"lote": [asdict(r) for r in recursos]}
        resumen = "; ".join(r.resumen_intento() for r in recursos)
        job = Job(
            operation=recursos[0].repositorio(), device=device_name,
            group_job_id=group_job_id, parameters=parametros,
            parameters_summary=resumen,
        )
        self._jobs.add(job)
        self._job_queue.dispatch_lote(recursos, device_name, actor, job.job_id)
        job_entry = {"device": device_name, "job_id": job.job_id, "status": job.status}
        return group_job_id, job_entry
