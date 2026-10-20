import logging

from fastapi import APIRouter, Depends

from app.composition import job_repository
from app.core.exceptions import NotFoundError
from app.core.response import ok
from app.core.scope import obtener_scope, require_authenticated
from app.models.visibility_scope import VisibilityScope

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/{group_job_id}",
    summary="Get group job",
    description=(
        "Return the aggregated status and per-device results of a group job. "
        "A group job represents one logical VLAN operation dispatched across N devices. "
        "Only the jobs on devices the caller can see are aggregated; a group "
        "with none visible returns 404, the same as a nonexistent one."
    ),
)
def get_group_job(
    group_job_id: str,
    current_user: dict = Depends(require_authenticated),
    scope: VisibilityScope = Depends(obtener_scope),
):
    resumen = job_repository.resumen_de_grupo(group_job_id, scope=scope)
    if resumen is None:
        raise NotFoundError(f"Group job '{group_job_id}' not found")
    return ok(resumen)
