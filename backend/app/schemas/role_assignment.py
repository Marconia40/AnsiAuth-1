from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


_VALID_ASSIGNMENT_ROLES = {"observer", "operator", "admin"}


class RoleAssignmentCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"site_id": 1, "device_group_id": 3, "role": "operator"}
    })

    site_id: int = Field(..., ge=1)
    device_group_id: Optional[int] = Field(default=None, ge=1)
    role: str

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in _VALID_ASSIGNMENT_ROLES:
            raise ValueError(
                f"role must be one of {sorted(_VALID_ASSIGNMENT_ROLES)}"
            )
        return v


class RoleAssignmentRead(BaseModel):
    id: int
    user_id: int
    site_id: int
    site_name: Optional[str] = None
    device_group_id: Optional[int] = None
    device_group_name: Optional[str] = None
    role: str
    created_at: datetime
    created_by_user_id: Optional[int] = None
    created_by_username: Optional[str] = None


class SystemAdminUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"is_system_admin": True}})

    is_system_admin: bool
