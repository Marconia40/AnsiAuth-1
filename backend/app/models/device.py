from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.vendors.base import VendorDriver

_VALID_VENDORS = {"cisco_ios", "huawei_vrp"}

_VALID_AUTH_METHODS = {"password", "key"}


@dataclass
class Device:
    name: str
    host: str
    vendor: str
    username: str
    encrypted_password: str
    platform: str = "ios"
    auth_method: str = "password"
    encrypted_private_key: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    device_group_id: Optional[int] = None
    device_group_name: Optional[str] = None

    _driver: "VendorDriver | None" = field(default=None, repr=False, compare=False, init=False)
    _password: "str | None" = field(default=None, repr=False, compare=False, init=False)
    _private_key: "str | None" = field(default=None, repr=False, compare=False, init=False)

    @classmethod
    def nuevo(
        cls, name: str, host: str, vendor: str, platform: str, username: str,
        encrypted_password: str, device_group_id: int, *,
        auth_method: str = "password", encrypted_private_key: "str | None" = None,
    ) -> "Device":
        if vendor not in _VALID_VENDORS:
            raise ValueError(
                f"Vendor '{vendor}' not supported. Valid values: {', '.join(sorted(_VALID_VENDORS))}"
            )
        if auth_method not in _VALID_AUTH_METHODS:
            raise ValueError(
                f"auth_method '{auth_method}' not supported. Valid values: {', '.join(sorted(_VALID_AUTH_METHODS))}"
            )
        return cls(
            name=name, host=host, vendor=vendor, platform=platform,
            username=username, encrypted_password=encrypted_password,
            device_group_id=device_group_id, auth_method=auth_method,
            encrypted_private_key=encrypted_private_key,
        )

    @property
    def driver(self) -> "VendorDriver":
        if self._driver is None:
            from app.composition import plugin_registry
            self._driver = plugin_registry.obtener(self.vendor)
        return self._driver

    @property
    def password(self) -> str:
        if self._password is None:
            from app.composition import secret_vault
            self._password = secret_vault.decrypt(self.encrypted_password)
        return self._password

    @property
    def private_key(self) -> "str | None":
        if self.encrypted_private_key is None:
            return None
        if self._private_key is None:
            from app.composition import secret_vault
            self._private_key = secret_vault.decrypt(self.encrypted_private_key)
        return self._private_key

    def actualizar(
        self, *, host: str | None = None, vendor: str | None = None,
        platform: str | None = None, username: str | None = None,
        password: str | None = None, auth_method: str | None = None,
        private_key: str | None = None, vault=None,
    ) -> None:
        if host is not None:
            self.host = host
        if vendor is not None:
            if vendor not in _VALID_VENDORS:
                raise ValueError(
                    f"Vendor '{vendor}' not supported. Valid values: {', '.join(sorted(_VALID_VENDORS))}"
                )
            self.vendor = vendor
        if platform is not None:
            self.platform = platform
        if username is not None:
            self.username = username
        if auth_method is not None:
            if auth_method not in _VALID_AUTH_METHODS:
                raise ValueError(
                    f"auth_method '{auth_method}' not supported. Valid values: {', '.join(sorted(_VALID_AUTH_METHODS))}"
                )
            self.auth_method = auth_method
        if password is not None:
            if vault is None:
                raise ValueError("actualizar(): password nuevo requiere vault")
            self.encrypted_password = vault.encrypt(password)
            self._password = None
        if private_key is not None:
            if vault is None:
                raise ValueError("actualizar(): private_key nueva requiere vault")
            self.encrypted_private_key = vault.encrypt(private_key)
            self._private_key = None
