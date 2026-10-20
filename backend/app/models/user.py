from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


@dataclass
class User:
    id: Optional[int]
    username: str
    hashed_password: str
    email: Optional[str] = None
    is_active: bool = True
    is_system_admin: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def nuevo(
        cls, username: str, password: str, email: str | None = None,
        is_system_admin: bool = False,
    ) -> "User":
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        return cls(
            id=None,
            username=username.lower(),
            hashed_password=_pwd_context.hash(password),
            email=email.lower() if email else None,
            is_active=True,
            is_system_admin=bool(is_system_admin),
        )

    def verificar_password(self, plain_password: str) -> bool:
        if not self.is_active:
            return False
        return _pwd_context.verify(plain_password, self.hashed_password)

    def cambiar_password(self, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")
        self.hashed_password = _pwd_context.hash(new_password)

    def actualizar(self, *, email: str | None = None, password: str | None = None) -> None:
        if email is not None:
            self.email = email.lower()
        if password is not None:
            self.cambiar_password(password)

    def desactivar(self) -> None:
        self.is_active = False

    def activar(self) -> None:
        self.is_active = True
