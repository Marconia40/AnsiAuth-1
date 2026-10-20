from __future__ import annotations

from app.models.port import Puerto
from app.services.vendors.base import VendorDriver

DEFAULT_PORTS: list[Puerto] = [
    Puerto(
        interface="GigabitEthernet0/0/1", description="Workstation-01",
        admin_up=True, operational_up=True, mode="access", access_vlan=10,
    ),
    Puerto(
        interface="GigabitEthernet0/0/2", description="Workstation-02",
        admin_up=True, operational_up=False, mode="access", access_vlan=20,
    ),
    Puerto(
        interface="GigabitEthernet0/0/24", description="Uplink to core",
        admin_up=True, operational_up=True, mode="trunk", access_vlan=1,
        allowed_vlans=[10, 20, 30],
    ),
]


class FakePuertoDriver(VendorDriver):
    def __init__(
        self, ports: "list[Puerto] | None" = None, fail_on=None,
        stateful: bool = False, mutate_before_fail: bool = False,
    ):
        self.ports = list(ports) if ports is not None else [
            Puerto.from_dict(p.to_dict()) for p in DEFAULT_PORTS
        ]
        self.fail_on = fail_on
        self.stateful = stateful
        self.mutate_before_fail = mutate_before_fail
        self.calls: list[tuple[str, "str | None", dict]] = []

    def _mutar_estado(self, op_key, vars):
        if not self.stateful:
            return
        puerto = next((p for p in self.ports if p.interface == vars.get("interface")), None)
        if puerto is None:
            return
        if op_key == "update_port_description":
            puerto.description = vars["description"]
        elif op_key == "set_port_admin_state":
            puerto.admin_up = vars["enabled"]
        elif op_key == "set_port_access_vlan":
            puerto.access_vlan = vars["vlan_id"]
        elif op_key == "set_storm_control":
            puerto.storm_control_enabled = vars["enabled"]
            puerto.storm_control_threshold = vars["threshold"] if vars["enabled"] else None
            puerto.storm_control_action = vars.get("action") if vars["enabled"] else None
            puerto.storm_control_trap = vars.get("trap") if vars["enabled"] else None
        elif op_key == "set_trunk_vlans_delta":
            actuales = set(puerto.allowed_vlans or [])
            puerto.allowed_vlans = sorted((actuales | set(vars.get("add", []))) - set(vars.get("remove", [])))
        elif op_key == "set_trunk_config_delta":
            actuales = set(puerto.allowed_vlans or [])
            puerto.allowed_vlans = sorted((actuales | set(vars.get("add", []))) - set(vars.get("remove", [])))
            if vars.get("pvid") is not None:
                puerto.access_vlan = vars["pvid"]
        elif op_key == "set_trunk_allowed_vlans":
            puerto.allowed_vlans = sorted(set(vars["vlan_list"]))
        elif op_key == "set_trunk_pvid_vlan":
            puerto.access_vlan = vars["vlan_id"]
        elif op_key == "set_trunk_mode":
            puerto.mode = "trunk"
            puerto.access_vlan = vars["native_vlan"]
            puerto.allowed_vlans = sorted(set(vars["vlan_list"]))
        elif op_key == "set_access_mode":
            puerto.mode = "access"
            puerto.access_vlan = vars["vlan_id"]
            puerto.allowed_vlans = None

    def _resultado_de_paso(self, op_key, vars):
        if self.fail_on and self.fail_on(op_key, vars):
            if self.mutate_before_fail:
                self._mutar_estado(op_key, vars)
            return {"rc": 1, "stdout": "", "stderr": "invalid input detected -- simulated failure", "success": False}
        self._mutar_estado(op_key, vars)
        return {"rc": 0, "stdout": "ok", "stderr": "", "success": True}

    def create_vlan(self, *a, **k):
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def delete_vlan(self, *a, **k):
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def update_vlan(self, *a, **k):
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def save_config(self, *a, **k):
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def get_vlans(self, *a, **k):
        return []

    def get_svis(self, *a, **k):
        return []

    def list_ports(self, device, password):
        return [Puerto.from_dict(p.to_dict()) for p in self.ports]

    def resolver_update_port_description(self, interface, description):
        return ("update_port_description", None, {"interface": interface, "description": description})

    def resolver_set_port_admin_state(self, interface, enabled):
        return ("set_port_admin_state", None, {"interface": interface, "enabled": enabled})

    def resolver_set_port_access_vlan(self, interface, vlan_id):
        return ("set_port_access_vlan", None, {"interface": interface, "vlan_id": vlan_id})

    def resolver_set_trunk_pvid_vlan(self, interface, vlan_id):
        return ("set_trunk_pvid_vlan", None, {"interface": interface, "vlan_id": vlan_id})

    def resolver_set_trunk_allowed_vlans(self, interface, vlan_list):
        return ("set_trunk_allowed_vlans", None, {"interface": interface, "vlan_list": list(vlan_list)})

    def resolver_set_trunk_config_delta(self, interface, pvid, add, remove):
        add, remove = sorted(set(add or [])), sorted(set(remove or []))
        if pvid is None and not add and not remove:
            raise ValueError("set_trunk_config_delta necesita un PVID o al menos una VLAN a agregar o quitar")
        return ("set_trunk_config_delta", None, {"interface": interface, "pvid": pvid, "add": add, "remove": remove})

    def resolver_set_trunk_vlans_delta(self, interface, add, remove):
        add, remove = sorted(set(add or [])), sorted(set(remove or []))
        if not add and not remove:
            raise ValueError("set_trunk_vlans_delta necesita al menos una VLAN a agregar o a quitar")
        variant = "both" if add and remove else ("add" if add else "remove")
        return ("set_trunk_vlans_delta", variant, {"interface": interface, "add": add, "remove": remove})

    def resolver_set_port_poe(self, interface, enabled):
        return ("set_port_poe", None, {"interface": interface, "enabled": enabled})

    def resolver_set_storm_control(self, interface, enabled, threshold, action="shutdown", trap=True):
        return ("set_storm_control", None, {
            "interface": interface, "enabled": enabled, "threshold": threshold,
            "action": action, "trap": trap,
        })

    def resolver_reset_port(self, interface):
        return ("reset_port", None, {"interface": interface})

    def resolver_set_access_mode(self, interface, vlan_id, *, viene_de_trunk_con_vlans=True):
        return ("set_access_mode", None, {"interface": interface, "vlan_id": vlan_id})

    def resolver_set_trunk_mode(self, interface, native_vlan, vlan_list):
        return ("set_trunk_mode", None, {
            "interface": interface, "native_vlan": native_vlan, "vlan_list": list(vlan_list),
        })

    def aplicar_paso(self, op_key, variant, vars, device, password):
        self.calls.append((op_key, variant, dict(vars)))
        return self._resultado_de_paso(op_key, vars)

    def aplicar_lote(self, pasos, device, password, *, op_label="lote"):
        for op_key, variant, vars in pasos:
            self.calls.append((op_key, variant, dict(vars)))
            resultado = self._resultado_de_paso(op_key, vars)
            if resultado["rc"] != 0:
                return resultado
        return {"rc": 0, "stdout": "ok", "stderr": "", "success": True}

    def update_port_description(self, interface, description, device, password):
        self.calls.append(("rollback:update_port_description", None, {"interface": interface, "description": description}))
        self._mutar_estado("update_port_description", {"interface": interface, "description": description})
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_port_admin_state(self, interface, enabled, device, password):
        self.calls.append(("rollback:set_port_admin_state", None, {"interface": interface, "enabled": enabled}))
        self._mutar_estado("set_port_admin_state", {"interface": interface, "enabled": enabled})
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_port_access_vlan(self, interface, vlan_id, device, password):
        self.calls.append(("rollback:set_port_access_vlan", None, {"interface": interface, "vlan_id": vlan_id}))
        self._mutar_estado("set_port_access_vlan", {"interface": interface, "vlan_id": vlan_id})
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_trunk_pvid_vlan(self, interface, vlan_id, device, password):
        self.calls.append(("rollback:set_trunk_pvid_vlan", None, {"interface": interface, "vlan_id": vlan_id}))
        self._mutar_estado("set_trunk_pvid_vlan", {"interface": interface, "vlan_id": vlan_id})
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_trunk_allowed_vlans(self, interface, vlan_list, device, password):
        self.calls.append(("rollback:set_trunk_allowed_vlans", None, {"interface": interface, "vlan_list": list(vlan_list)}))
        self._mutar_estado("set_trunk_allowed_vlans", {"interface": interface, "vlan_list": list(vlan_list)})
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_port_poe(self, interface, enabled, device, password):
        self.calls.append(("rollback:set_port_poe", None, {"interface": interface, "enabled": enabled}))
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_storm_control(self, interface, enabled, threshold, action, trap, device, password):
        self.calls.append(("rollback:set_storm_control", None, {
            "interface": interface, "enabled": enabled, "threshold": threshold,
            "action": action, "trap": trap,
        }))
        self._mutar_estado("set_storm_control", {
            "interface": interface, "enabled": enabled, "threshold": threshold,
            "action": action, "trap": trap,
        })
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def reset_port(self, interface, device, password):
        self.calls.append(("rollback:reset_port", None, {"interface": interface}))
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_access_mode(self, interface, vlan_id, device, password, *, viene_de_trunk_con_vlans=True):
        self.calls.append(("rollback:set_access_mode", None, {"interface": interface, "vlan_id": vlan_id}))
        self._mutar_estado("set_access_mode", {"interface": interface, "vlan_id": vlan_id})
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}

    def set_trunk_mode(self, interface, native_vlan, vlan_list, device, password):
        self.calls.append(("rollback:set_trunk_mode", None, {
            "interface": interface, "native_vlan": native_vlan, "vlan_list": list(vlan_list),
        }))
        self._mutar_estado("set_trunk_mode", {
            "interface": interface, "native_vlan": native_vlan, "vlan_list": list(vlan_list),
        })
        return {"rc": 0, "stdout": "", "stderr": "", "success": True}


def get_or_create_site(name: str):
    from app.composition import site_repository
    from app.db.models import SiteModel
    from app.db.session import get_session

    with get_session() as session:
        row = session.query(SiteModel.id).filter_by(name=name).first()
    if row is not None:
        return site_repository.get(row[0])
    return site_repository.crear_con_grupo_default(name, kind="REGULAR")


def get_or_create_device(name: str, *, site_name: str, vendor: str = "cisco_ios", host: str = "192.0.2.10"):
    from app.composition import device_repository, inventory
    from app.core.exceptions import ValidationError

    site = get_or_create_site(site_name)
    try:
        return inventory.register(
            name=name, host=host, vendor=vendor, platform="ios" if vendor == "cisco_ios" else "vrp",
            username="admin", password="pw",
            site_id=site.id, device_group_id=site.default_group_id,
            actor={"username": "admin"},
        )
    except ValidationError:
        return device_repository.get(name)


class StubUnimplementedDriver(VendorDriver):
    def create_vlan(self, *a, **k):
        raise NotImplementedError

    def delete_vlan(self, *a, **k):
        raise NotImplementedError

    def update_vlan(self, *a, **k):
        raise NotImplementedError

    def save_config(self, *a, **k):
        raise NotImplementedError

    def get_vlans(self, *a, **k):
        return []

    def list_ports(self, *a, **k):
        return []
