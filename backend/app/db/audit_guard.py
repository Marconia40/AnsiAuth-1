from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models import AuditLogModel


class AuditImmutabilityError(RuntimeError):
    pass


def _block_updates(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    for obj in session.dirty:
        if isinstance(obj, AuditLogModel) and session.is_modified(obj, include_collections=False):
            raise AuditImmutabilityError(
                f"audit_logs row id={obj.id} is immutable — "
                "append a new row via AuditRepository.append() instead "
                "(set parent_audit_id to chain it to this one)"
            )


def install() -> None:
    if not event.contains(Session, "before_flush", _block_updates):
        event.listen(Session, "before_flush", _block_updates)
