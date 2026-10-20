from dataclasses import asdict


class JobQueue:
    def dispatch(self, recurso: "RecursoGestionable", device_name: str, actor: str, job_id: str) -> None:
        from app.tasks import ejecutar_task
        ejecutar_task.delay(asdict(recurso), recurso.repositorio(), device_name, actor, job_id)

    def dispatch_lote(self, recursos: "list[RecursoGestionable]", device_name: str, actor: str, job_id: str) -> None:
        from app.tasks import ejecutar_lote_task
        recursos_dict = [asdict(r) for r in recursos]
        ejecutar_lote_task.delay(recursos_dict, recursos[0].repositorio(), device_name, actor, job_id)
