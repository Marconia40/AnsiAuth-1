import os
from datetime import timedelta

from celery import Celery, Task
from celery.signals import worker_process_init
from app.core.config import settings


class TareaDeSistema(Task):
    def __call__(self, *args, **kwargs):
        from app.core.rls_context import system_context

        with system_context():
            return super().__call__(*args, **kwargs)


celery_app = Celery(
    "ansiauth",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    task_cls=TareaDeSistema,
)

_SYNC_STALE_INTERVAL_MIN = int(os.getenv("SYNC_STALE_INTERVAL_MIN", "20"))

_ORPHAN_JOB_SWEEP_MIN = int(os.getenv("ORPHAN_JOB_SWEEP_MIN", "5"))


def agenda_periodica() -> dict:
    agenda = {
        "recuperar-jobs-huerfanos": {
            "task": "ansiauth.jobs.recuperar_huerfanos",
            "schedule": timedelta(minutes=_ORPHAN_JOB_SWEEP_MIN),
        },
    }
    if os.getenv("SYNC_PERIODIC_ENABLED", "false").lower() in ("true", "1"):
        agenda["sync-stale-devices"] = {
            "task": "ansiauth.device.sync_stale",
            "schedule": timedelta(minutes=_SYNC_STALE_INTERVAL_MIN),
        }
    return agenda


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() in ("true", "1"),
    include=["app.tasks"],
    beat_schedule=agenda_periodica(),
)


@worker_process_init.connect
def _init_db_for_worker(**kwargs):
    from app.core.rls_context import install_worker_system_context
    from app.db.session import init_db
    init_db(settings.DATABASE_URL)
    install_worker_system_context()
