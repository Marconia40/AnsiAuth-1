from __future__ import annotations

import re
from dataclasses import dataclass

_VLAN_NAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')
_VLAN_NAME_ERROR = 'Invalid VLAN name. Only letters, numbers, ".", "_" and "-" are allowed.'


def _validate_vlan_id_range(vlan_id: int) -> None:
    if vlan_id < 1 or vlan_id > 4094:
        raise ValueError(f"VLAN ID {vlan_id} is out of range (1-4094)")


def _validate_vlan_not_reserved(vlan_id: int) -> None:
    reserved = [1, 1002, 1003, 1004, 1005]
    if vlan_id in reserved:
        raise ValueError(f"VLAN {vlan_id} is reserved")


def _validate_vlan_name(name: str) -> None:
    if len(name) > 32:
        raise ValueError("VLAN name must not exceed 32 characters")
    if not _VLAN_NAME_RE.match(name):
        raise ValueError(_VLAN_NAME_ERROR)


def _validate_description(description: str) -> None:
    if len(description) > 64:
        raise ValueError("Description must not exceed 64 characters")
    if not _VLAN_NAME_RE.match(description):
        raise ValueError(_VLAN_NAME_ERROR)


@dataclass
class VLAN:
    vlan_id: int
    name: str = ""
    status: str | None = None
    device: str = ""
    eliminar: bool = False

    def __post_init__(self) -> None:
        _validate_vlan_id_range(self.vlan_id)
        _validate_vlan_not_reserved(self.vlan_id)

    def validar(self) -> None:
        if self.eliminar:
            return
        _validate_vlan_name(self.name)

    def reconciliar(self, device: "Device") -> dict:
        vlans_actuales = device.driver.get_vlans(device, device.password)
        existente = next((v for v in vlans_actuales if v.vlan_id == self.vlan_id), None)
        return {
            "existed": existente is not None,
            "name": existente.name if existente is not None else None,
        }

    @staticmethod
    def reconciliar_lote(recursos: "list[VLAN]", device: "Device") -> "list[dict]":
        vlans_actuales = device.driver.get_vlans(device, device.password)
        por_id = {v.vlan_id: v for v in vlans_actuales}
        return [
            {
                "existed": r.vlan_id in por_id,
                "name": por_id[r.vlan_id].name if r.vlan_id in por_id else None,
                "actual": por_id.get(r.vlan_id),
            }
            for r in recursos
        ]

    def resolver_paso(
        self, device: "Device", actual: "VLAN | None",
    ) -> "tuple[str, str | None, dict] | None":
        if self.eliminar:
            if actual is None:
                return None
            return device.driver.resolver_delete_vlan(self.vlan_id)
        if actual is not None and actual.name == self.name:
            return None
        if actual is not None:
            return device.driver.resolver_update_vlan(self.vlan_id, self.name)
        return device.driver.resolver_create_vlan(self.vlan_id, self.name)

    NECESITA_ESTADO_FRESCO_ROLLBACK = True

    def _debe_revertir(
        self, existia: "bool | None", nombre_previo: "str | None",
        existe_ahora: "bool | None", nombre_ahora: "str | None",
    ) -> bool:
        if self.eliminar:
            if not existia:
                return False
            return existe_ahora is None or not existe_ahora
        if existe_ahora is None:
            return False
        if existia and nombre_previo != self.name:
            return bool(existe_ahora) and nombre_ahora == self.name
        if not existia:
            return bool(existe_ahora) and nombre_ahora == self.name
        return False

    def resolver_rollback(
        self, pre_state: dict, device: "Device", actual_ahora: "VLAN | None" = None,
    ) -> "tuple[list, object | None]":
        existia = pre_state.get("existed")
        nombre_previo = pre_state.get("name")
        existe_ahora = actual_ahora is not None
        nombre_ahora = actual_ahora.name if actual_ahora is not None else None
        if not self._debe_revertir(existia, nombre_previo, existe_ahora, nombre_ahora):
            return [], None
        vlan_id = self.vlan_id
        if self.eliminar:
            paso = device.driver.resolver_create_vlan(vlan_id, nombre_previo or self.name)

            def verificar(actual):
                return actual is not None
        elif existia:
            paso = device.driver.resolver_update_vlan(vlan_id, nombre_previo)

            def verificar(actual):
                return actual is not None and actual.name == nombre_previo
        else:
            paso = device.driver.resolver_delete_vlan(vlan_id)

            def verificar(actual):
                return actual is None
        return [paso], verificar

    def aplicar(self, device: "Device", pre_state: "dict | None" = None) -> dict:
        if pre_state is None:
            pre_state = self.reconciliar(device)
        if self.eliminar:
            if not pre_state["existed"]:
                return {"rc": 0, "success": True, "changed": False, "noop": True, "accion": "eliminar_vlan"}
            resultado = device.driver.delete_vlan(self.vlan_id, device, device.password)
            return {**resultado, "accion": "eliminar_vlan"}
        if pre_state["existed"] and pre_state["name"] == self.name:
            return {"rc": 0, "success": True, "changed": False, "noop": True, "accion": "crear_vlan"}
        if pre_state["existed"] and pre_state["name"] != self.name:
            resultado = device.driver.update_vlan(self.vlan_id, self.name, device, device.password)
            return {**resultado, "accion": "actualizar_vlan"}
        resultado = device.driver.create_vlan(self.vlan_id, self.name, device, device.password)
        return {**resultado, "accion": "crear_vlan"}

    def ejecutar_rollback(self, pre_state: dict, device: "Device") -> "tuple[bool, bool | None]":
        existia = pre_state.get("existed")
        nombre_previo = pre_state.get("name")
        if self.eliminar and not existia:
            return False, None
        try:
            ahora = self.reconciliar(device)
            existe_ahora, nombre_ahora = ahora["existed"], ahora["name"]
        except Exception:
            existe_ahora, nombre_ahora = None, None
        if not self._debe_revertir(existia, nombre_previo, existe_ahora, nombre_ahora):
            return False, None
        try:
            if self.eliminar:
                resultado = device.driver.create_vlan(self.vlan_id, nombre_previo or self.name, device, device.password)
            elif existia and nombre_previo != self.name:
                resultado = device.driver.update_vlan(self.vlan_id, nombre_previo, device, device.password)
            elif not existia:
                resultado = device.driver.delete_vlan(self.vlan_id, device, device.password)
            else:
                return False, None
        except Exception:
            return True, False

        if resultado.get("rc", 1) != 0:
            return True, False

        try:
            actuales = device.driver.get_vlans(device, device.password)
            actual = next((v for v in actuales if v.vlan_id == self.vlan_id), None)
            if self.eliminar:
                verificado = actual is not None
            elif existia and nombre_previo != self.name:
                verificado = actual is not None and actual.name == nombre_previo
            else:
                verificado = actual is None
        except Exception:
            verificado = False
        return True, verificado

    def repositorio(self) -> str:
        return "vlan"

    def resumen_intento(self) -> str:
        if self.eliminar:
            return f"Delete VLAN {self.vlan_id}"
        return f"VLAN {self.vlan_id}: set name to '{self.name}'"

    def to_dict(self) -> dict:
        return {"vlan_id": self.vlan_id, "name": self.name}

    @classmethod
    def from_dict(cls, data: dict) -> VLAN:
        return cls(
            vlan_id=data["vlan_id"],
            name=data["name"],
            status=data.get("status"),
        )
