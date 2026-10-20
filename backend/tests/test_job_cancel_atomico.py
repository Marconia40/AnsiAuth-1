import uuid
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import TransicionInvalidaError
from app.models.job import Job


@pytest.fixture()
def device_con_permisos():
    from app.db.models import DeviceGroupModel, DeviceModel, RoleAssignmentModel, SiteModel, UserModel
    from app.db.session import get_session

    tag = uuid.uuid4().hex[:6]
    nombre = f"cancel-dev-{tag}"
    with get_session() as session:
        site = SiteModel(name=f"cancel-site-{tag}", kind="REGULAR")
        session.add(site); session.flush()
        group = DeviceGroupModel(name=f"Default-cancel-{tag}", site_id=site.id, is_default=True)
        session.add(group); session.flush()
        site.default_group_id = group.id
        session.add(DeviceModel(name=nombre, host="10.9.9.9", vendor="cisco", platform="ios",
                                username="u", encrypted_password="x", device_group_id=group.id))
        grants = []
        for username in ("operator", "observer"):
            user = session.query(UserModel).filter_by(username=username).first()
            ra = RoleAssignmentModel(user_id=user.id, site_id=site.id, device_group_id=None, role=username)
            session.add(ra); grants.append(ra)
        session.flush()
        site_id, grant_ids = site.id, [g.id for g in grants]
    yield nombre
    with get_session() as session:
        session.query(RoleAssignmentModel).filter(RoleAssignmentModel.id.in_(grant_ids)).delete(synchronize_session=False)
        session.query(DeviceModel).filter_by(name=nombre).delete(synchronize_session=False)
        row = session.query(SiteModel).filter_by(id=site_id).first()
        row.default_group_id = None
        session.flush()
        session.query(DeviceGroupModel).filter_by(site_id=site_id).delete(synchronize_session=False)
        session.query(SiteModel).filter_by(id=site_id).delete(synchronize_session=False)


def _repo():
    from app.composition import job_repository
    return job_repository


def test_job_en_ejecucion_no_puede_cancelarse():
    job = Job()
    job.marcar_iniciado()
    with pytest.raises(TransicionInvalidaError):
        job.cancelar()


def test_cancelar_job_en_ejecucion_responde_409(client):
    job = Job()
    job.marcar_iniciado()
    _repo().add(job)
    response = client.post(f"/api/v1/jobs/{job.job_id}/cancel")
    assert response.status_code == 409
    assert _repo().get(job.job_id).status == "running"


def test_observador_no_puede_cancelar(observer_client, device_con_permisos):
    job = _repo().add(Job(device=device_con_permisos))
    response = observer_client.post(f"/api/v1/jobs/{job.job_id}/cancel")
    assert response.status_code == 403
    assert _repo().get(job.job_id).status == "pending"


def test_operador_cancela_job_pendiente(operator_client, device_con_permisos):
    job = _repo().add(Job(device=device_con_permisos))
    response = operator_client.post(f"/api/v1/jobs/{job.job_id}/cancel")
    assert response.status_code == 200
    assert _repo().get(job.job_id).status == "cancelled"


def test_cancelar_pierde_si_el_worker_ya_lo_inicio():
    repo = _repo()
    job = repo.add(Job())
    copia_api = repo.get(job.job_id)
    copia_worker = repo.get(job.job_id)
    assert repo.iniciar_si_pendiente(copia_worker) is True
    assert repo.cancelar_si_pendiente(copia_api) is False
    assert repo.get(job.job_id).status == "running"


def test_worker_no_inicia_un_job_ya_cancelado():
    repo = _repo()
    job = repo.add(Job())
    copia_worker = repo.get(job.job_id)
    copia_api = repo.get(job.job_id)
    assert repo.cancelar_si_pendiente(copia_api) is True
    assert repo.iniciar_si_pendiente(copia_worker) is False
    assert repo.get(job.job_id).status == "cancelled"


def test_orquestador_no_ejecuta_un_job_cancelado_en_la_base():
    from app.services.orquestador import Orquestador

    repo = _repo()
    job = repo.add(Job(device="mock_device"))
    copia_worker = repo.get(job.job_id)
    assert repo.cancelar_si_pendiente(repo.get(job.job_id)) is True

    orq = object.__new__(Orquestador)
    orq._device_repo = MagicMock()
    orq._jobs = repo
    orq._coordinador = MagicMock()
    orq._eventos = MagicMock()
    orq._repos = {}
    orq.ejecutar(MagicMock(), "mock_device", "tester", copia_worker)

    orq._coordinador.bloquear.assert_not_called()
    assert repo.get(job.job_id).status == "cancelled"


def _job_en_grupo(grupo, estado):
    job = Job(group_job_id=grupo)
    if estado == "cancelled":
        job.cancelar()
    elif estado in ("completed", "failed"):
        job.marcar_iniciado()
        if estado == "completed":
            job.marcar_completado({"rc": 0})
        else:
            job.marcar_fallido("error de prueba")
    return _repo().add(job)


@pytest.mark.parametrize("estados, esperado", [
    (["cancelled", "cancelled"], "cancelled"),
    (["completed", "cancelled"], "partial_success"),
    (["failed", "cancelled"], "failed"),
    (["completed", "completed"], "completed"),
])
def test_estado_de_lote_con_cancelados(estados, esperado):
    grupo = str(uuid.uuid4())
    for e in estados:
        _job_en_grupo(grupo, e)
    resumen = _repo().resumen_de_grupo(grupo)
    assert resumen["status"] == esperado
    assert resumen["execution_summary"]["cancelled"] == estados.count("cancelled")
