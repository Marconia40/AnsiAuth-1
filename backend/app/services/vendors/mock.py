from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models.port import Puerto
from app.models.vlan import VLAN
from app.services.vendors.base import VendorDriver

if TYPE_CHECKING:
    from app.models.device import Device

logger = logging.getLogger(__name__)


_INITIAL_MOCK_VLANS: list[VLAN] = [
    VLAN(vlan_id=10, name="MGMT"),
    VLAN(vlan_id=20, name="DATA"),
    VLAN(vlan_id=30, name="VOICE"),
]

_mock_vlans: list[VLAN] = [
    VLAN(vlan_id=v.vlan_id, name=v.name, status=v.status) for v in _INITIAL_MOCK_VLANS
]


def reset_mock_vlans() -> None:
    _mock_vlans.clear()
    _mock_vlans.extend(
        VLAN(vlan_id=v.vlan_id, name=v.name, status=v.status) for v in _INITIAL_MOCK_VLANS
    )


_INITIAL_MOCK_PORTS: list[Puerto] = [
    Puerto(
        interface="GigabitEthernet0/0/1",
        description="Workstation-01",
        admin_up=True,
        operational_up=True,
        mode="access",
        access_vlan=10,
        allowed_vlans=None,
    ),
    Puerto(
        interface="GigabitEthernet0/0/2",
        description="Workstation-02",
        admin_up=True,
        operational_up=False,
        mode="access",
        access_vlan=20,
        allowed_vlans=None,
    ),
    Puerto(
        interface="GigabitEthernet0/0/24",
        description="Uplink to core",
        admin_up=True,
        operational_up=True,
        mode="trunk",
        access_vlan=1,
        allowed_vlans=[10, 20, 30],
    ),
]


class MockVendor(VendorDriver):
    def create_vlan(self, vlan_id: int, name: str, device: "Device", password: str) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure"}
        logger.info("Mock: VLAN %s created on %s", vlan_id, device.name)
        return {"rc": 0, "stdout": f"Simulated VLAN {vlan_id} created", "stderr": ""}

    def delete_vlan(self, vlan_id: int, device: "Device", password: str) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure"}
        _mock_vlans[:] = [v for v in _mock_vlans if v.vlan_id != vlan_id]
        logger.info("Mock: VLAN %s deleted on %s", vlan_id, device.name)
        return {"rc": 0, "stdout": f"Simulated VLAN {vlan_id} deleted", "stderr": ""}

    def update_vlan(self, vlan_id: int, name: str, device: "Device", password: str) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure"}
        logger.info("Mock: VLAN %s updated on %s", vlan_id, device.name)
        return {
            "rc": 0,
            "stdout": f"Simulated VLAN {vlan_id} description updated to '{name}'",
            "stderr": "",
        }

    def save_config(self, device: "Device", password: str) -> dict:
        logger.info("Mock: save config on %s", device.name)
        return {"rc": 0, "stdout": "Simulated config saved", "stderr": ""}

    def get_vlans(self, device: "Device", password: str) -> list[VLAN]:
        logger.info("Mock: returning hardcoded VLAN list")
        return list(_mock_vlans)

    def list_ports(self, device: "Device", password: str) -> list["Puerto"]:
        if device.name == "fail_device":
            raise RuntimeError(f"Simulated port listing failure on device '{device.name}'")
        logger.info(
            "Mock: returning %d ports for device=%s", len(_INITIAL_MOCK_PORTS), device.name
        )
        return [Puerto.from_dict(p.to_dict()) for p in _INITIAL_MOCK_PORTS]

    def update_port_description(
        self, interface: str, description: str, device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: update description on interface=%s device=%s description=%r",
            interface, device.name, description,
        )
        return {"rc": 0, "stdout": "Simulated description updated", "stderr": "", "success": True}

    def set_port_admin_state(
        self, interface: str, enabled: bool, device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set admin state on interface=%s device=%s enabled=%s",
            interface, device.name, enabled,
        )
        return {"rc": 0, "stdout": "Simulated admin state applied", "stderr": "", "success": True}

    def set_port_access_vlan(
        self, interface: str, vlan_id: int, device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set access VLAN on interface=%s device=%s vlan_id=%d",
            interface, device.name, vlan_id,
        )
        return {"rc": 0, "stdout": "Simulated access VLAN applied", "stderr": "", "success": True}

    def set_trunk_pvid_vlan(
        self, interface: str, vlan_id: int, device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set trunk PVID on interface=%s device=%s vlan_id=%d",
            interface, device.name, vlan_id,
        )
        return {"rc": 0, "stdout": "Simulated trunk PVID applied", "stderr": "", "success": True}

    def set_trunk_allowed_vlans(
        self, interface: str, vlan_list: list[int], device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set trunk VLANs on interface=%s device=%s vlans=%s",
            interface, device.name, vlan_list,
        )
        return {"rc": 0, "stdout": "Simulated trunk VLANs applied", "stderr": "", "success": True}

    def set_port_poe(
        self, interface: str, enabled: bool, device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set PoE on interface=%s device=%s enabled=%s",
            interface, device.name, enabled,
        )
        return {"rc": 0, "stdout": "Simulated PoE state applied", "stderr": "", "success": True}

    def set_storm_control(
        self, interface: str, enabled: bool, threshold: "float | None", action: str, trap: bool,
        device: "Device", password: str,
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set storm-control on interface=%s device=%s enabled=%s threshold=%s action=%s trap=%s",
            interface, device.name, enabled, threshold, action, trap,
        )
        return {"rc": 0, "stdout": "Simulated storm-control applied", "stderr": "", "success": True}

    def reset_port(
        self, interface: str, device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: reset port to defaults on interface=%s device=%s",
            interface, device.name,
        )
        return {"rc": 0, "stdout": "Simulated port reset applied", "stderr": "", "success": True}

    def set_access_mode(
        self, interface: str, vlan_id: int, device: "Device", password: str,
        *, viene_de_trunk_con_vlans: bool = True,
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set access mode on interface=%s device=%s vlan_id=%d",
            interface, device.name, vlan_id,
        )
        return {"rc": 0, "stdout": "Simulated access mode applied", "stderr": "", "success": True}

    def set_trunk_mode(
        self, interface: str, native_vlan: int, vlan_list: list[int], device: "Device", password: str
    ) -> dict:
        if device.name == "fail_device":
            return {"rc": 1, "stdout": "", "stderr": "Simulated Ansible failure", "success": False}
        logger.info(
            "Mock: set trunk mode on interface=%s device=%s native_vlan=%d vlans=%s",
            interface, device.name, native_vlan, vlan_list,
        )
        return {"rc": 0, "stdout": "Simulated trunk mode applied", "stderr": "", "success": True}
