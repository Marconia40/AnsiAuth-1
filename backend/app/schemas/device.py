import ipaddress
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")
_IPV4_LIKE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def _validate_host(v: str) -> str:
    try:
        ipaddress.ip_address(v)
        return v
    except ValueError:
        pass
    if _IPV4_LIKE.match(v):
        raise ValueError(f"'{v}' is not a valid IP address")
    if _HOSTNAME_RE.match(v):
        return v
    raise ValueError(f"'{v}' is not a valid IP address or hostname")


class DeviceCreate(BaseModel):
    name: str
    host: str
    vendor: str
    platform: str = "ios"
    username: str
    auth_method: Literal["password", "key"] = "password"
    password: Optional[str] = None
    private_key: Optional[str] = None
    site_id: int = Field(..., ge=1)
    device_group_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("host")
    @classmethod
    def validate_host(cls, v):
        return _validate_host(v)

    @model_validator(mode="after")
    def _validar_credencial(self) -> "DeviceCreate":
        if self.auth_method == "password":
            if not self.password:
                raise ValueError("password is required when auth_method='password'")
            if self.private_key:
                raise ValueError("private_key cannot be set when auth_method='password'")
        else:
            if not self.private_key:
                raise ValueError("private_key is required when auth_method='key'")
            if self.password:
                raise ValueError("password cannot be set when auth_method='key'")
        return self


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"host": "192.168.1.20", "username": "netops"}},
    )

    host: Optional[str] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    auth_method: Optional[Literal["password", "key"]] = None
    private_key: Optional[str] = None

    @field_validator("host")
    @classmethod
    def validate_host(cls, v):
        if v is None:
            return v
        return _validate_host(v)

    @model_validator(mode="after")
    def _inferir_auth_method(self) -> "DeviceUpdate":
        if self.password and self.private_key:
            raise ValueError("cannot set both password and private_key in the same call")
        if self.auth_method is None:
            if self.private_key:
                self.auth_method = "key"
            elif self.password:
                self.auth_method = "password"
        elif self.auth_method == "password" and self.private_key:
            raise ValueError("private_key cannot be set when auth_method='password'")
        elif self.auth_method == "key" and self.password:
            raise ValueError("password cannot be set when auth_method='key'")
        elif self.auth_method == "key" and not self.private_key:
            raise ValueError("private_key is required when setting auth_method='key'")
        return self

    @model_validator(mode="before")
    @classmethod
    def _reject_scope_keys(cls, values):
        if isinstance(values, dict):
            forbidden = {k for k in ("site_id", "device_group_id") if k in values}
            if forbidden:
                raise ValueError(
                    f"{sorted(forbidden)} cannot be set via PUT /devices/{{name}}; "
                    "use POST /devices/{name}/move to change a device's group or site"
                )
        return values


class DevicePublic(BaseModel):
    id: str
    name: str
    host: str
    vendor: str
    platform: str
    username: str
    auth_method: str = "password"
    site_id: int
    site_name: str
    device_group_id: int
    device_group_name: str


class DeviceMove(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {"device_group_id": 5},
            {"device_group_id": None},
        ]
    })

    device_group_id: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Target group ID. Pass null to move the device to its current "
            "site's Default group."
        ),
    )
