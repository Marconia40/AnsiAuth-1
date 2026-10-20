from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import LoginAttemptModel
from app.db.session import get_session

USERNAME_FAIL_LIMIT: int = 5
USERNAME_LOCKOUT_MINUTES: int = 15
IP_FAIL_LIMIT: int = 20
IP_LOCKOUT_HOURS: int = 1


class LoginAttemptRepository:
    def esta_bloqueado(self, username: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=USERNAME_LOCKOUT_MINUTES)
        with get_session() as session:
            count = (
                session.query(LoginAttemptModel)
                .filter(
                    LoginAttemptModel.username == username.lower(),
                    LoginAttemptModel.succeeded == False,  # noqa: E712
                    LoginAttemptModel.attempted_at >= cutoff,
                )
                .count()
            )
        return count >= USERNAME_FAIL_LIMIT

    def ip_bloqueada(self, ip_address: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=IP_LOCKOUT_HOURS)
        with get_session() as session:
            count = (
                session.query(LoginAttemptModel)
                .filter(
                    LoginAttemptModel.ip_address == ip_address,
                    LoginAttemptModel.succeeded == False,  # noqa: E712
                    LoginAttemptModel.attempted_at >= cutoff,
                )
                .count()
            )
        return count >= IP_FAIL_LIMIT

    def registrar_intento(self, username: str, ip_address: str, exitoso: bool) -> None:
        with get_session() as session:
            session.add(
                LoginAttemptModel(
                    username=username.lower(),
                    ip_address=ip_address,
                    attempted_at=datetime.now(timezone.utc),
                    succeeded=exitoso,
                )
            )

    def purgar_antiguos(self, dias: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=dias)
        with get_session() as session:
            deleted = (
                session.query(LoginAttemptModel)
                .filter(LoginAttemptModel.attempted_at < cutoff)
                .delete(synchronize_session=False)
            )
        return deleted

    def resetear(self, username: str) -> int:
        with get_session() as session:
            return (
                session.query(LoginAttemptModel)
                .filter(
                    LoginAttemptModel.username == username.lower(),
                    LoginAttemptModel.succeeded == False,  # noqa: E712
                )
                .delete(synchronize_session=False)
            )

    def resetear_todo(self) -> None:
        with get_session() as session:
            session.query(LoginAttemptModel).delete(synchronize_session=False)
