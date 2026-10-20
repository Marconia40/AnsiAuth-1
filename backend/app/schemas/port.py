from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

PortMode = Literal["access", "trunk", "unknown"]


class PortRead(BaseModel):
    name: str = Field(..., description="Canonical interface identifier as reported by the device.")
    name_full: str = Field(
        ...,
        description=(
            "Unabbreviated interface identifier (e.g. '10GE6/0/43' or "
            "'GigabitEthernet0/1' instead of 'GE6/0/43'/'Gi0/1'). Large "
            "devices reuse the same trailing port number across multiple "
            "line-card prefixes (10GE5/0/43, 10GE6/0/43, ...), so UI views "
            "that identify a port by number alone must use this field, not "
            "'name', to stay unambiguous."
        ),
    )
    description: Optional[str] = Field(
        None, description="Operator-supplied description, or null if none configured."
    )
    admin_up: Optional[bool] = Field(
        None, description="Administrative state (True = not shut down)."
    )
    operational_up: Optional[bool] = Field(
        None, description="Line-protocol state (True = link up at L1/L2)."
    )
    mode: PortMode = Field(
        "unknown",
        description=(
            "Normalized switchport mode. 'unknown' is used when the platform "
            "reports a value that does not cleanly map to access/trunk "
            "(e.g. Huawei VRP 'hybrid')."
        ),
    )
    kind: Literal["physical", "aggregate"] = Field(
        "physical",
        description=(
            "'aggregate' for a link-aggregation interface (Eth-Trunk / "
            "Port-channel) rather than a single physical port. PoE and "
            "storm-control cannot be configured on an aggregate."
        ),
    )
    access_vlan: Optional[int] = Field(
        None,
        description=(
            "VLAN ID assigned to an access port, or the native VLAN of a "
            "trunk port. Null when unknown."
        ),
    )
    allowed_vlans: Optional[list[int]] = Field(
        None,
        description=(
            "For trunk ports, the list of VLAN IDs permitted on the trunk. "
            "Null for access ports or when the device does not expose this."
        ),
    )
    storm_control_enabled: Optional[bool] = Field(
        None,
        description=(
            "Whether storm-control is administratively enabled on this port. "
            "Null when the driver could not determine the state (e.g. the "
            "device returned no matching lines, or the platform expresses it "
            "in a form the parser doesn't yet recognise)."
        ),
    )
    storm_control_threshold: Optional[float] = Field(
        None,
        description=(
            "Storm-control threshold in percent (0-100). Null when unknown, "
            "or when storm-control is configured in a non-percent unit like "
            "pps/bps -- our write path only produces percent-form, so that "
            "only happens with configs preexisting to this system."
        ),
    )
    storm_control_action: Optional[str] = Field(
        None,
        description=(
            "What happens to the port on a storm -- 'filter' (drop excess "
            "traffic, port stays up) or 'shutdown' (port goes down). Null "
            "when unknown or storm-control is disabled."
        ),
    )
    storm_control_trap: Optional[bool] = Field(
        None,
        description="Whether an SNMP trap fires on a storm. Null when unknown or storm-control is disabled.",
    )


class _PortTargetRequest(BaseModel):
    interface: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Vendor-native interface name (e.g. 'GigabitEthernet1/0/1').",
    )


class PortDescriptionUpdateRequest(_PortTargetRequest):
    description: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="New description text.",
    )


class PortDescriptionClearRequest(_PortTargetRequest):
    pass


class PortAdminStateUpdateRequest(_PortTargetRequest):
    enabled: bool = Field(
        ...,
        description="Desired admin state — True to enable, False to disable.",
    )


class PortAccessVlanUpdateRequest(_PortTargetRequest):
    vlan_id: int = Field(
        ...,
        ge=1,
        le=4094,
        description="Access VLAN ID (1-4094, excluding reserved 1002-1005).",
    )


class PortTrunkVlansUpdateRequest(_PortTargetRequest):
    mode: Literal["replace", "add", "remove"] = Field(
        ...,
        description=(
            "How vlans is applied to the current trunk config. "
            "'replace' sets the list exactly; 'add' unions with current; "
            "'remove' subtracts from current."
        ),
    )
    vlans: list[int] = Field(
        ...,
        min_length=1,
        description=(
            "VLAN IDs to apply (1-4094, excluding reserved 1002-1005). "
            "Must be a non-empty list. Duplicates are ignored."
        ),
    )


class PortSetAccessModeRequest(_PortTargetRequest):
    access_vlan: int = Field(
        ...,
        ge=1,
        le=4094,
        description="Access VLAN ID to assign (1-4094).",
    )


class PortSetTrunkModeRequest(_PortTargetRequest):
    native_vlan: int = Field(
        ...,
        ge=1,
        le=4094,
        description="Native VLAN (PVID) for the trunk.",
    )
    allowed_vlans: list[int] = Field(
        ...,
        min_length=1,
        description="Trunk allowed VLANs (non-empty).",
    )


class PortShutdownRequest(_PortTargetRequest):
    pass


class PortEnableRequest(_PortTargetRequest):
    pass


class PortPoeUpdateRequest(_PortTargetRequest):
    enabled: bool = Field(
        ...,
        description="Desired PoE state — True to enable, False to disable.",
    )


class PortStormControlUpdateRequest(_PortTargetRequest):
    enabled: bool = Field(
        ...,
        description="Desired storm-control state — True to enable, False to disable.",
    )
    threshold_percent: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description="Broadcast threshold as a percentage of bandwidth (0-100). Required when enabled=True.",
    )
    action: Optional[Literal["filter", "shutdown"]] = Field(
        default=None,
        description=(
            "What happens to the port on a storm -- 'filter' (drop excess, "
            "port stays up) or 'shutdown' (port goes down). Only meaningful "
            "with enabled=True; defaults to 'shutdown' (today's hardcoded "
            "behavior) when omitted."
        ),
    )
    trap: Optional[bool] = Field(
        default=None,
        description=(
            "Whether an SNMP trap fires on a storm. Only meaningful with "
            "enabled=True; defaults to True (today's hardcoded behavior) "
            "when omitted."
        ),
    )


class PortBatchChangeItem(_PortTargetRequest):
    description: Optional[str] = Field(None, max_length=200)
    admin_up: Optional[bool] = None
    mode: Optional[Literal["access", "trunk"]] = None
    access_vlan: Optional[int] = Field(None, ge=1, le=4094)
    allowed_vlans: Optional[list[int]] = None
    allowed_vlan_operation: Literal["replace", "add", "remove"] = Field(
        "replace",
        description=(
            "Only meaningful with allowed_vlans. If omitted the list REPLACES the "
            "port's allowed VLANs (only the difference is sent to the device). Send "
            "'add' or 'remove' to change a few VLANs without listing the rest."
        ),
    )
    poe_enabled: Optional[bool] = None
    storm_control_enabled: Optional[bool] = None
    storm_control_threshold: Optional[float] = Field(None, ge=0, le=100)
    storm_control_action: Optional[Literal["filter", "shutdown"]] = None
    storm_control_trap: Optional[bool] = None


class PortBatchRequest(BaseModel):
    changes: list[PortBatchChangeItem] = Field(..., min_length=1)


class PortResetRequest(_PortTargetRequest):
    pass
