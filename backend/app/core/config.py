import os
from typing import Annotated, List, Optional

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

load_dotenv()

_DB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "db"))
_ANSIBLE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ansible")
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    FERNET_KEY: Optional[str] = None
    JWT_SECRET_KEY: Optional[str] = None

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=20, ge=1)
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(default=240, ge=1)

    REFRESH_TOKEN_IDLE_MINUTES: int = Field(default=15, ge=1)
    SESSION_ABSOLUTE_MAX_HOURS: int = Field(default=2, ge=1)
    ELEVATED_TOKEN_EXPIRE_MINUTES: int = Field(default=5, ge=1, le=15)

    EXECUTION_MODE: str = "mock"

    DATABASE_URL: str = f"sqlite:///{_DB_DIR}/app.db"

    BOOTSTRAP_ADMIN_USER: str = "admin"
    BOOTSTRAP_ADMIN_PASSWORD: Optional[str] = None

    RATE_LIMIT_PER_IP: int = Field(default=20, ge=1)
    RATE_LIMIT_PER_USER: int = Field(default=200, ge=1)
    RATE_LIMIT_LOGIN: int = Field(default=5, ge=1)

    SSL_CERTFILE: Optional[str] = None
    SSL_KEYFILE: Optional[str] = None

    AUDIT_RETENTION_DAYS: int = Field(default=90, ge=1)

    CLEANUP_INTERVAL_HOURS: int = Field(default=6, ge=1)
    ARTIFACT_RETENTION_DAYS: int = Field(default=30, ge=1)
    LOGIN_ATTEMPT_RETENTION_DAYS: int = Field(default=7, ge=1)

    LOG_FORMAT: str = "text"
    METRICS_ENABLED: bool = False

    REDIS_URL: str = "redis://localhost:6379/0"

    CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "strict"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_origins(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def _validate_samesite(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"strict", "lax", "none"}:
            raise ValueError(
                f"COOKIE_SAMESITE must be one of 'strict', 'lax', 'none' "
                f"(got: {value!r})"
            )
        return normalized

    @field_validator("EXECUTION_MODE")
    @classmethod
    def _validate_execution_mode(cls, value: str) -> str:
        if value not in {"mock", "real"}:
            raise ValueError(
                f"EXECUTION_MODE must be 'mock' or 'real' (got: {value!r})"
            )
        return value


try:
    settings = Settings()
except Exception as exc:
    raise RuntimeError(f"Invalid configuration: {exc}") from exc


FERNET_KEY = settings.FERNET_KEY
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_MINUTES = settings.REFRESH_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_IDLE_MINUTES = settings.REFRESH_TOKEN_IDLE_MINUTES
SESSION_ABSOLUTE_MAX_HOURS = settings.SESSION_ABSOLUTE_MAX_HOURS
ELEVATED_TOKEN_EXPIRE_MINUTES = settings.ELEVATED_TOKEN_EXPIRE_MINUTES
EXECUTION_MODE = settings.EXECUTION_MODE
DATABASE_URL = settings.DATABASE_URL
BOOTSTRAP_ADMIN_USER = settings.BOOTSTRAP_ADMIN_USER
BOOTSTRAP_ADMIN_PASSWORD = settings.BOOTSTRAP_ADMIN_PASSWORD
RATE_LIMIT_PER_IP = settings.RATE_LIMIT_PER_IP
RATE_LIMIT_PER_USER = settings.RATE_LIMIT_PER_USER
RATE_LIMIT_LOGIN = settings.RATE_LIMIT_LOGIN
SSL_CERTFILE = settings.SSL_CERTFILE
SSL_KEYFILE = settings.SSL_KEYFILE
AUDIT_RETENTION_DAYS = settings.AUDIT_RETENTION_DAYS
CLEANUP_INTERVAL_HOURS = settings.CLEANUP_INTERVAL_HOURS
ARTIFACT_RETENTION_DAYS = settings.ARTIFACT_RETENTION_DAYS
LOGIN_ATTEMPT_RETENTION_DAYS = settings.LOGIN_ATTEMPT_RETENTION_DAYS
CORS_ORIGINS = settings.CORS_ORIGINS
COOKIE_SECURE = settings.COOKIE_SECURE
COOKIE_SAMESITE = settings.COOKIE_SAMESITE
LOG_FORMAT = settings.LOG_FORMAT
METRICS_ENABLED = settings.METRICS_ENABLED
REDIS_URL = settings.REDIS_URL

ANSIBLE_BASE_PATH = _ANSIBLE_DIR
INVENTORY_PATH = os.path.join(_ANSIBLE_DIR, "inventory", "inventory.ini")
