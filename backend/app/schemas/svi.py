from __future__ import annotations

import ipaddress
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _validar_cidr(value: str, version: int) -> str:
    interfaz = ipaddress.ip_interface(value)
    if interfaz.version != version:
        raise ValueError(f"expected an IPv{version} address, got {value!r}")
    return value


def _validar_ip_plana(value: str) -> str:
    ipaddress.ip_address(value)
    return value


class SVIRead(BaseModel):
    vlan_id: int = Field(..., description="VLAN ID -- identidad real de la interfaz (Vlan{id}/Vlanif{id}).")
    description: Optional[str] = Field(None, description="Descripción configurada, o null si no hay.")
    admin_up: Optional[bool] = Field(None, description="Estado administrativo (True = no shutdown).")
    operational_up: Optional[bool] = Field(None, description="Estado operacional real reportado por el device.")
    ipv4_address: Optional[str] = Field(None, description="Dirección IPv4 primaria en formato CIDR, o null si no configurada.")
    ipv4_address_secondary: Optional[list[str]] = Field(None, description="Direcciones IPv4 secundarias en formato CIDR, o null si no hay ninguna.")
    ipv6_address: Optional[str] = Field(None, description="Dirección IPv6 en formato CIDR, o null si no configurada.")
    acl_in: Optional[str] = Field(None, description="Nombre/número de ACL aplicada en sentido entrante, o null.")
    acl_out: Optional[str] = Field(None, description="Nombre/número de ACL aplicada en sentido saliente, o null.")
    dhcp_relay_servers: Optional[list[str]] = Field(None, description="Lista de IPs de DHCP relay, o null si no hay ninguna.")


class _SVITargetRequest(BaseModel):
    vlan_id: int = Field(..., ge=1, le=4094, description="VLAN ID de la interfaz (1-4094).")


class SVICreateRequest(_SVITargetRequest):
    description: Optional[str] = Field(
        default=None, max_length=240,
        description="Descripción opcional a aplicar al crear la interfaz (RF-INTERV-01).",
    )


class SVIDeleteRequest(_SVITargetRequest):
    pass


class SVIAdminStateUpdateRequest(_SVITargetRequest):
    enabled: bool = Field(..., description="Estado administrativo deseado -- True para activar, False para desactivar.")


class SVIDescriptionUpdateRequest(_SVITargetRequest):
    description: str = Field(..., min_length=1, max_length=240, description="Nueva descripción.")


class SVIDescriptionClearRequest(_SVITargetRequest):
    pass


class SVIIpv4UpdateRequest(_SVITargetRequest):
    ipv4_address: str = Field(..., description="Dirección IPv4 en formato CIDR (ej. '10.10.10.11/24').")

    @field_validator("ipv4_address")
    @classmethod
    def _validar_ipv4(cls, v: str) -> str:
        return _validar_cidr(v, 4)


class SVIIpv4ClearRequest(_SVITargetRequest):
    pass


class SVIIpv6UpdateRequest(_SVITargetRequest):
    ipv6_address: str = Field(..., description="Dirección IPv6 en formato CIDR (ej. '2001:db8::1/64').")

    @field_validator("ipv6_address")
    @classmethod
    def _validar_ipv6(cls, v: str) -> str:
        return _validar_cidr(v, 6)


class SVIIpv6ClearRequest(_SVITargetRequest):
    pass


class SVIAclUpdateRequest(_SVITargetRequest):
    direction: Literal["in", "out"] = Field(..., description="Sentido de la ACL -- 'in' o 'out'.")
    acl_name: str = Field(..., min_length=1, description="Nombre/número de la ACL a asignar.")


class SVIAclClearRequest(_SVITargetRequest):
    direction: Literal["in", "out"] = Field(..., description="Sentido de la ACL a desasignar -- 'in' o 'out'.")


class SVIBatchRequest(BaseModel):
    description: Optional[str] = Field(None, max_length=240)
    admin_up: Optional[bool] = None
    ipv4_address: Optional[str] = None
    ipv6_address: Optional[str] = None
    acl_in: Optional[str] = Field(None, description="Nombre/número de ACL, o '' para desasignar.")
    acl_out: Optional[str] = Field(None, description="Nombre/número de ACL, o '' para desasignar.")
    dhcp_relay_add: Optional[str] = Field(None, description="IP de 1 servidor DHCP relay a agregar.")
    dhcp_relay_remove: Optional[str] = Field(None, description="IP de 1 servidor DHCP relay a eliminar.")
    ipv4_secondary_add: Optional[str] = Field(None, description="1 dirección IPv4 secundaria (CIDR) a agregar.")
    ipv4_secondary_remove: Optional[str] = Field(None, description="1 dirección IPv4 secundaria (CIDR) a eliminar.")

    @field_validator("ipv4_address")
    @classmethod
    def _validar_ipv4_o_vacio(cls, v: "str | None") -> "str | None":
        if v:
            _validar_cidr(v, 4)
        return v

    @field_validator("ipv6_address")
    @classmethod
    def _validar_ipv6_o_vacio(cls, v: "str | None") -> "str | None":
        if v:
            _validar_cidr(v, 6)
        return v

    @field_validator("dhcp_relay_add", "dhcp_relay_remove")
    @classmethod
    def _validar_dhcp_relay_ip(cls, v: "str | None") -> "str | None":
        if v:
            _validar_ip_plana(v)
        return v

    @field_validator("ipv4_secondary_add", "ipv4_secondary_remove")
    @classmethod
    def _validar_ipv4_secondary_cidr(cls, v: "str | None") -> "str | None":
        if v:
            _validar_cidr(v, 4)
        return v

    @model_validator(mode="after")
    def _validar_dhcp_relay_exclusivo(self) -> "SVIBatchRequest":
        if self.dhcp_relay_add is not None and self.dhcp_relay_remove is not None:
            raise ValueError("cannot set dhcp_relay_add and dhcp_relay_remove in the same call")
        return self

    @model_validator(mode="after")
    def _validar_ipv4_secondary_exclusivo(self) -> "SVIBatchRequest":
        if self.ipv4_secondary_add is not None and self.ipv4_secondary_remove is not None:
            raise ValueError("cannot set ipv4_secondary_add and ipv4_secondary_remove in the same call")
        return self


class SVIDhcpRelayAddRequest(_SVITargetRequest):
    server: str = Field(..., description="IP de un servidor DHCP relay a agregar.")

    @field_validator("server")
    @classmethod
    def _validar_ip(cls, v: str) -> str:
        return _validar_ip_plana(v)


class SVIDhcpRelayRemoveRequest(_SVITargetRequest):
    server: str = Field(..., description="IP de un servidor DHCP relay a eliminar.")

    @field_validator("server")
    @classmethod
    def _validar_ip(cls, v: str) -> str:
        return _validar_ip_plana(v)


class SVIIpv4SecondaryAddRequest(_SVITargetRequest):
    address: str = Field(..., description="Dirección IPv4 secundaria a agregar, en formato CIDR (ej. '10.10.10.12/24').")

    @field_validator("address")
    @classmethod
    def _validar_ip(cls, v: str) -> str:
        return _validar_cidr(v, 4)


class SVIIpv4SecondaryRemoveRequest(_SVITargetRequest):
    address: str = Field(..., description="Dirección IPv4 secundaria a eliminar, en formato CIDR (ej. '10.10.10.12/24').")

    @field_validator("address")
    @classmethod
    def _validar_ip(cls, v: str) -> str:
        return _validar_cidr(v, 4)
