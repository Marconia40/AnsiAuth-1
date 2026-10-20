from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.core.config import (
    ANSIBLE_BASE_PATH,
    REFRESH_TOKEN_IDLE_MINUTES,
    SESSION_ABSOLUTE_MAX_HOURS,
)
from app.db.models import RefreshTokenModel
from app.db.session import get_session

logger = logging.getLogger(__name__)


class CleanupScheduler:
    def __init__(self, login_attempt_repo):
        self._login_attempts = login_attempt_repo

    def purgar_artefactos(self, dias: int = 30) -> int:
        artifacts_dir = os.path.join(ANSIBLE_BASE_PATH, "artifacts")
        if not os.path.isdir(artifacts_dir):
            logger.info("Artifact purge skipped: %s does not exist", artifacts_dir)
            return 0

        cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=dias)).timestamp()
        removed = 0
        for entry in os.scandir(artifacts_dir):
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime < cutoff_ts:
                    shutil.rmtree(entry.path)
                    removed += 1
            except OSError as exc:
                logger.warning("Failed to remove artifact %s: %s", entry.path, exc)

        logger.info(
            "Artifact purge complete: removed=%d retention_days=%d dir=%s",
            removed, dias, artifacts_dir,
        )
        return removed

    def limpiar_refresh_tokens(self) -> int:
        now = datetime.now(timezone.utc)
        idle_cutoff = now - timedelta(minutes=REFRESH_TOKEN_IDLE_MINUTES)
        absolute_cutoff = now - timedelta(hours=SESSION_ABSOLUTE_MAX_HOURS)
        with get_session() as session:
            deleted = (
                session.query(RefreshTokenModel)
                .filter(
                    or_(
                        RefreshTokenModel.expires_at < now,
                        RefreshTokenModel.last_used_at < idle_cutoff,
                        RefreshTokenModel.session_started_at < absolute_cutoff,
                    )
                )
                .delete(synchronize_session=False)
            )
        logger.info("Refresh-token sweep complete: deleted=%d", deleted)
        return deleted

    def limpiar_intentos_login(self, dias: int = 7) -> int:
        return self._login_attempts.purgar_antiguos(dias)

    def ejecutar_todo(self, artifact_retention_days: int = 30, login_attempt_retention_days: int = 7) -> dict:
        summary: dict = {}
        for name, func in (
            ("artifacts", lambda: self.purgar_artefactos(artifact_retention_days)),
            ("refresh_tokens", self.limpiar_refresh_tokens),
            ("login_attempts", lambda: self.limpiar_intentos_login(login_attempt_retention_days)),
        ):
            try:
                summary[name] = func()
            except Exception:
                logger.exception("Cleanup routine %r failed", name)
                summary[name] = None
        return summary
