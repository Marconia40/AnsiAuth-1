from __future__ import annotations

import inspect
import ipaddress
import logging
import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.svi import SVI
    from app.models.port import Puerto
    from app.models.vlan import VLAN
    from app.models.global_config import GlobalConfig

logger = logging.getLogger(__name__)


RUIDO_BENIGNO: "tuple[re.Pattern, ...]" = (
    re.compile(r"%\s*access vlan does not exist\.\s*creating vlan\s*\d*", re.IGNORECASE),
    re.compile(r"\]y\r?\n\s*\^\r?\nError: Unrecognized command found at '\^' position\.", re.IGNORECASE),
)


def limpiar_ruido_benigno(texto: str) -> str:
    for patron in RUIDO_BENIGNO:
        texto = patron.sub("", texto or "")
    return texto


PATRONES_SIN_CONEXION: tuple[str, ...] = (
    "connection refused",
    "connectionrefusederror",
    "[errno 111]",
    "unable to connect",
    "no route to host",
    "network is unreachable",
    "[errno 113]",
)

PATRONES_NEGOCIACION_SSH: tuple[str, ...] = (
    "unable to negotiate",
    "no matching key exchange method",
    "no matching host key type",
    "no matching cipher",
)


def _no_conecto(resultado: "dict | None", error: "BaseException | None") -> bool:
    if error is not None:
        texto = f"{type(error).__name__}: {error}"
    elif resultado is None or resultado.get("rc", 1) == 0:
        return False
    elif any((s or "").strip() for s in (resultado.get("stdouts") or [])):
        return False
    else:
        texto = f"{resultado.get('stderr') or ''} {resultado.get('stdout') or ''}"
    texto = texto.lower()
    return any(p in texto for p in (*PATRONES_SIN_CONEXION, *PATRONES_NEGOCIACION_SSH))


class AlcanceEscritura:
    def __init__(self) -> None:
        self.intentos = 0
        self.sin_conexion = 0

    def registrar(self, resultado: "dict | None" = None, error: "BaseException | None" = None) -> None:
        self.intentos += 1
        if _no_conecto(resultado, error):
            self.sin_conexion += 1

    @property
    def nunca_llego(self) -> bool:
        return self.intentos > 0 and self.sin_conexion == self.intentos


_alcance_actual: "ContextVar[AlcanceEscritura | None]" = ContextVar("alcance_escritura", default=None)


@contextmanager
def rastrear_escrituras() -> Iterator[AlcanceEscritura]:
    alcance = AlcanceEscritura()
    token = _alcance_actual.set(alcance)
    try:
        yield alcance
    finally:
        _alcance_actual.reset(token)


def registrar_intento_escritura(
    resultado: "dict | None" = None, error: "BaseException | None" = None,
) -> None:
    alcance = _alcance_actual.get()
    if alcance is not None:
        alcance.registrar(resultado, error)


_ERROR_RE = re.compile(r"^\s*(Error:|%\s)", re.MULTILINE)

_ERROR_PATTERNS: "dict[str, re.Pattern]" = {
    "cisco_ios": re.compile(
        r"%\s*Error|invalid input|(?:incomplete|ambiguous) command|"
        r"connection timed out|[^\r\n]+ not found|bad mask|"
        r"bad secret|command authorization failed|"
        r"overlaps with|informational:|command rejected",
        re.IGNORECASE,
    ),
    "huawei_vrp": re.compile(
        r"%\s*Error:|^%\s*\w+|%\s*Bad secret|invalid input|"
        r"(?:incomplete|ambiguous) command|connection timed out|"
        r"[^\r\n]+ not found|syntax error|unknown command|"
        r"Error\[\d+\]:|Error:",
        re.IGNORECASE | re.MULTILINE,
    ),
}


def _tiene_error(texto: str, vendor: "str | None" = None) -> bool:
    patron = _ERROR_PATTERNS.get(vendor, _ERROR_RE)
    return bool(patron.search(limpiar_ruido_benigno(texto)))


_COMMIT_NO_SOPORTADO_RE = re.compile(
    r"\]commit\r?\n\s*\^\r?\nError: Unrecognized command(?: found at '\^' position\.)?",
    re.IGNORECASE,
)


NO_CONFIRMADO = "did not confirm the operation"


def _confirmar_exito(resultado: dict, patron: "str | None") -> dict:
    if not patron:
        return resultado
    if re.search(patron, resultado.get("stdout") or "", re.IGNORECASE):
        if resultado.get("success"):
            return resultado
        return {**resultado, "rc": 0, "success": True, "stderr": ""}
    if resultado.get("success"):
        return {
            **resultado, "rc": 1, "success": False,
            "stderr": f"The device {NO_CONFIRMADO} (expected: {patron})",
        }
    return resultado


def _solo_rechazo_commit(error_text: str, vendor: "str | None" = None) -> bool:
    if not _COMMIT_NO_SOPORTADO_RE.search(error_text):
        return False
    residual = _COMMIT_NO_SOPORTADO_RE.sub("", error_text)
    return not _tiene_error(residual, vendor)


def _comandos_desde_extravars(extravars: dict) -> "list[str]":
    if "lines" in extravars:
        parents = extravars.get("parents")
        return ([parents] if parents else []) + list(extravars["lines"])
    if "command_block" in extravars:
        return extravars["command_block"].split("\n")
    if "commands" in extravars:
        return list(extravars["commands"])
    if "command_blocks" in extravars:
        out: "list[str]" = []
        for block in extravars["command_blocks"]:
            out.extend(block.split("\n"))
        return out
    if "config_steps" in extravars:
        out: "list[str]" = []
        for step in extravars["config_steps"]:
            if step.get("parents"):
                out.append(step["parents"])
            out.extend(step.get("lines", []))
        return out
    return []


class VendorDriver(ABC):
    _PLAYBOOK: str
    _NETWORK_OS: str
    _CONNECTION: str = "network_cli"

    def _build_inventory(self, device: Device, password: str) -> str:
        from app.services import ansible_service
        return ansible_service.build_inventory(
            device.name, device.host, device.username, password,
            network_os=self._NETWORK_OS, connection=self._CONNECTION,
        )

    def _ejecutar(self, extravars: dict, device: Device, password: str) -> dict:
        if device.auth_method == "key":
            from app.services import ssh_direct_service
            return ssh_direct_service.run_direct(extravars, device)
        from app.services import ansible_service
        return ansible_service.run_playbook(
            playbook=self._PLAYBOOK,
            extravars={**extravars, "device": device.name},
            inventory=self._build_inventory(device, password),
            vendor=device.vendor,
        )

    def _aplicar(self, extravars: dict, device: Device, password: str, *, op_label: str) -> dict:
        import traceback

        logger.info("%s: %s on device=%s", type(self).__name__, op_label, device.name)
        try:
            try:
                result = self._ejecutar(extravars, device, password)
            except Exception as exc:
                registrar_intento_escritura(error=exc)
                raise
            registrar_intento_escritura(result)
            normalized = {**result, "success": result.get("rc", 1) == 0}
            comandos = _comandos_desde_extravars(extravars)
            if comandos:
                normalized["commands"] = comandos
            if normalized["success"]:
                logger.info("%s: %s OK on device=%s", type(self).__name__, op_label, device.name)
            else:
                logger.error(
                    "%s: %s FAILED on device=%s — %s",
                    type(self).__name__, op_label, device.name,
                    result.get("stderr") or result.get("stdout"),
                )
            return normalized
        except Exception as exc:
            logger.exception(
                "FULL %s TRACEBACK [%s device=%s]: %s\n%s",
                type(self).__name__.upper(), op_label, device.name, str(exc), traceback.format_exc(),
            )
            raise

    _UNSUPPORTED_COMMAND_MARKERS = ("% Invalid input", "Error: Unrecognized command")

    def _leer(
        self,
        commands: list[str],
        device: Device,
        password: str,
        *,
        partial_ok: bool = False,
    ) -> list[str]:
        logger.info(
            "%s: run %d command(s) on device=%s (partial_ok=%s)",
            type(self).__name__, len(commands), device.name, partial_ok,
        )
        extravars = {"commands": commands}
        if partial_ok:
            extravars["tolerate_command_errors"] = True
        result = self._ejecutar(extravars, device, password)
        stdouts = result.get("stdouts") or []
        if result["rc"] != 0:
            error = result.get("stderr") or result.get("stdout") or "playbook exited non-zero"
            if partial_ok and result.get("session_complete", True) and any(s.strip() for s in stdouts):
                logger.warning(
                    "%s: read on device=%s reported failure but captured %d/%d command output(s); "
                    "returning them for per-command handling (error was: %s)",
                    type(self).__name__, device.name, len(stdouts), len(commands), error,
                )
                return stdouts
            logger.error("%s: read failed on device=%s — %s", type(self).__name__, device.name, error)
            raise RuntimeError(f"Cannot read state on device '{device.name}': {error}")
        if not stdouts:
            raise RuntimeError(f"Cannot read state on device '{device.name}': no command output returned")
        if partial_ok and len(commands) > 1 and not any(s.strip() for s in stdouts):
            logger.error(
                "%s: read on device=%s returned rc=0 but every command's output is empty -- "
                "treating it as an unreachable device, not as an empty one", type(self).__name__, device.name,
            )
            raise RuntimeError(
                f"Cannot read state on device '{device.name}': every command returned empty output "
                f"(device unreachable or the session was cut)"
            )
        return stdouts

    @classmethod
    def _filter_unsupported(
        cls,
        stdouts: list[str],
        commands: list[str],
        device: Device,
    ) -> list[str]:
        cleaned = []
        for cmd, out in zip(commands, stdouts):
            if any(marker in out for marker in cls._UNSUPPORTED_COMMAND_MARKERS):
                logger.info(
                    "%s: device=%s does not support %r -- treating as absent feature",
                    cls.__name__, device.name, cmd,
                )
                cleaned.append("")
            else:
                cleaned.append(out)
        if len(stdouts) > len(commands):
            cleaned.extend(stdouts[len(commands):])
        return cleaned

    _commands_cache: dict | None = None

    @classmethod
    def _cargar_comandos(cls) -> dict:
        if cls._commands_cache is None:
            import yaml
            path = Path(inspect.getfile(cls)).parent / "commands.yaml"
            with open(path, encoding="utf-8") as f:
                cls._commands_cache = yaml.safe_load(f)
        return cls._commands_cache

    def _lineas_repetidas(self, step: dict, vars: dict) -> list[str]:
        repeat = step.get("repeat")
        if not repeat:
            return []
        items = vars.get(repeat["over"]) or []
        lineas: list[str] = []
        if items:
            lineas += [l.format(**vars) for l in repeat.get("prefix_if_nonempty", [])]
            lineas += [
                repeat["line"].format(item=item, index=i, **vars) for i, item in enumerate(items)
            ]
            lineas += [l.format(**vars) for l in repeat.get("suffix_if_nonempty", [])]
        else:
            lineas += [l.format(**vars) for l in repeat.get("if_empty", [])]
        return lineas

    def _renderizar_paso(self, step: dict, vars: dict) -> dict:
        extra = self._lineas_repetidas(step, vars)
        trailer = [l.format(**vars) for l in step.get("trailer", [])]
        if "commands" in step:
            extravars = {"commands": [c.format(**vars) for c in step["commands"]] + extra + trailer}
        elif "block" in step:
            todas = [c.format(**vars) for c in step["block"]] + extra + trailer
            extravars = {"command_block": "\n".join(todas)}
        else:
            todas = [c.format(**vars) for c in step["lines"]] + extra + trailer
            extravars = {"lines": todas}
            if "parents" in step:
                extravars["parents"] = step["parents"].format(**vars)
        if "match" in step:
            extravars["match"] = step["match"]
        return extravars

    def _ejecutar_paso(self, step: dict, vars: dict, device: Device, password: str, *, op_label: str) -> dict:
        extravars = self._renderizar_paso(step, vars)
        return self._aplicar(extravars, device, password, op_label=op_label)

    @staticmethod
    def _vars_tras_alternativa(vars: dict, alt: dict) -> dict:
        if "interface_full" in vars and "{interface_full}" in repr(alt):
            return {**vars, "interface": vars["interface_full"]}
        return vars

    def _aplicar_desde_template(
        self, op_key: str, vars: dict, device: Device, password: str, *, variant: str | None = None,
    ) -> dict:
        entry = self._cargar_comandos()[op_key]
        if variant is not None:
            entry = entry[variant]
        patron_exito = entry.get("success_pattern")
        resultado = _confirmar_exito(
            self._ejecutar_paso(entry["primary"], vars, device, password, op_label=op_key), patron_exito,
        )
        alternativas_restantes = list(entry.get("alternatives", []))
        intento = 0
        while not resultado["success"] and alternativas_restantes:
            error_text = (resultado.get("stderr") or "") + (resultado.get("stdout") or "")
            error_text = error_text.replace("\\r\\n", "\r\n").replace("\\r", "\r").replace("\\n", "\n")
            if _solo_rechazo_commit(error_text, getattr(device, "vendor", None)):
                logger.info(
                    "%s: %s -- el único error fue el rechazo de 'commit' (equipo sin "
                    "candidate-config): las líneas ya se aplicaron, no se reenvía on device=%s",
                    type(self).__name__, op_key, device.name,
                )
                return {**resultado, "rc": 0, "success": True, "stderr": ""}
            indice_match = next(
                (i for i, alt in enumerate(alternativas_restantes)
                 if re.search(alt["triggered_by_error"], error_text)),
                None,
            )
            if indice_match is None:
                break
            alt = alternativas_restantes.pop(indice_match)
            vars = self._vars_tras_alternativa(vars, alt)
            intento += 1
            logger.info(
                "%s: %s failed (attempt %d), retrying with known alternative on device=%s",
                type(self).__name__, op_key, intento, device.name,
            )
            resultado = _confirmar_exito(
                self._ejecutar_paso(alt, vars, device, password, op_label=f"{op_key} (alt {intento})"),
                patron_exito,
            )
        return resultado

    def aplicar_paso(self, op_key: str, variant: "str | None", vars: dict, device: Device, password: str) -> dict:
        return self._aplicar_desde_template(op_key, vars, device, password, variant=variant)

    @staticmethod
    def _combinar_pasos_renderizados(renders: list[dict]) -> dict:
        if "command_block" in renders[0]:
            return {"command_blocks": [r["command_block"] for r in renders]}
        return {"config_steps": renders}

    def aplicar_lote(
        self, pasos: list[tuple[str, "str | None", dict]], device: Device, password: str,
        *, op_label: str = "lote",
    ) -> dict:
        comandos = self._cargar_comandos()
        entradas: list[tuple[str, "str | None", dict, dict]] = []
        renders: list[dict] = []
        alternativas_restantes: list[list[dict]] = []
        for op_key, variant, vars in pasos:
            entry = comandos[op_key]
            if variant is not None:
                entry = entry[variant]
            entradas.append((op_key, variant, entry, vars))
            renders.append(self._renderizar_paso(entry["primary"], vars))
            alternativas_restantes.append(list(entry.get("alternatives", [])))

        resultado = self._aplicar(
            self._combinar_pasos_renderizados(renders), device, password, op_label=op_label,
        )
        intento = 0
        while not resultado["success"]:
            error_text = (resultado.get("stderr") or "") + (resultado.get("stdout") or "")
            error_text = error_text.replace("\\r\\n", "\r\n").replace("\\r", "\r").replace("\\n", "\n")

            if _solo_rechazo_commit(error_text, getattr(device, "vendor", None)):
                logger.info(
                    "%s: %s -- el único error fue el rechazo de 'commit' (equipo sin "
                    "candidate-config): las líneas ya se aplicaron, no se reenvía el lote on device=%s",
                    type(self).__name__, op_label, device.name,
                )
                return {**resultado, "rc": 0, "success": True, "stderr": ""}

            hubo_alternativa = False
            for i, (op_key, variant, entry, vars) in enumerate(entradas):
                restantes = alternativas_restantes[i]
                indice_match = next(
                    (j for j, alt in enumerate(restantes) if re.search(alt["triggered_by_error"], error_text)),
                    None,
                )
                if indice_match is None:
                    continue
                alt = restantes.pop(indice_match)
                vars = self._vars_tras_alternativa(vars, alt)
                entradas[i] = (op_key, variant, entry, vars)
                renders[i] = self._renderizar_paso(alt, vars)
                hubo_alternativa = True
            if not hubo_alternativa:
                return resultado

            intento += 1
            logger.info(
                "%s: %s failed (attempt %d), retrying lote with known alternative(s) on device=%s",
                type(self).__name__, op_label, intento, device.name,
            )
            resultado = self._aplicar(
                self._combinar_pasos_renderizados(renders), device, password, op_label=f"{op_label} (alt {intento})",
            )
        return resultado

    @staticmethod
    def _compress_to_ranges(vlans: list[int]) -> list[tuple[int, int]]:
        if not vlans:
            return []
        sv = sorted(set(vlans))
        ranges: list[tuple[int, int]] = []
        start = sv[0]
        prev = sv[0]
        for v in sv[1:]:
            if v == prev + 1:
                prev = v
            else:
                ranges.append((start, prev))
                start = v
                prev = v
        ranges.append((start, prev))
        return ranges

    @staticmethod
    def _is_description_empty(description: str) -> bool:
        return not bool(description and description.strip())


    @abstractmethod
    def create_vlan(self, vlan_id: int, name: str, device: Device, password: str) -> dict:
        pass

    @abstractmethod
    def delete_vlan(self, vlan_id: int, device: Device, password: str) -> dict:
        pass

    @abstractmethod
    def update_vlan(self, vlan_id: int, name: str, device: Device, password: str) -> dict:
        pass

    @abstractmethod
    def save_config(self, device: Device, password: str) -> dict:
        pass


    @abstractmethod
    def get_vlans(self, device: Device, password: str) -> list[VLAN]:
        pass

    def list_vlans(self, device: Device, password: str) -> list[VLAN]:
        return self.get_vlans(device, password)

    def get_vlan(self, vlan_id: int, device: Device, password: str) -> VLAN | None:
        return next(
            (v for v in self.list_vlans(device, password) if v.vlan_id == vlan_id),
            None,
        )


    def read_core_state(
        self, device: Device, password: str,
    ) -> tuple[list[VLAN], list[Puerto], list[SVI]]:
        vlans = self.get_vlans(device, password)
        ports = self.list_ports(device, password)
        svis = self.get_svis(device, password)
        return vlans, ports, svis


    @abstractmethod
    def list_ports(self, device: Device, password: str) -> list[Puerto]:
        pass


    def update_port_description(
        self,
        interface: str,
        description: str,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement update_port_description yet"
        )

    def set_port_admin_state(
        self,
        interface: str,
        enabled: bool,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_port_admin_state yet"
        )

    def set_port_access_vlan(
        self,
        interface: str,
        vlan_id: int,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_port_access_vlan yet"
        )

    def set_trunk_pvid_vlan(
        self,
        interface: str,
        vlan_id: int,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_trunk_pvid_vlan yet"
        )

    def set_trunk_allowed_vlans(
        self,
        interface: str,
        vlan_list: list[int],
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_trunk_allowed_vlans yet"
        )

    def set_port_poe(
        self,
        interface: str,
        enabled: bool,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_port_poe yet"
        )

    def set_storm_control(
        self,
        interface: str,
        enabled: bool,
        threshold: "float | None",
        action: str,
        trap: bool,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_storm_control yet"
        )

    def reset_port(
        self,
        interface: str,
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement reset_port yet"
        )

    def set_access_mode(
        self,
        interface: str,
        vlan_id: int,
        device: Device,
        password: str,
        *,
        viene_de_trunk_con_vlans: bool = True,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_access_mode yet"
        )

    def set_trunk_mode(
        self,
        interface: str,
        native_vlan: int,
        vlan_list: list[int],
        device: Device,
        password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_trunk_mode yet"
        )


    def create_svi(self, vlan_id: int, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement create_svi yet"
        )

    def delete_svi(self, vlan_id: int, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement delete_svi yet"
        )

    def set_svi_admin_state(self, vlan_id: int, enabled: bool, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_admin_state yet"
        )

    def set_svi_description(self, vlan_id: int, description: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_description yet"
        )

    def set_svi_ipv4(self, vlan_id: int, ipv4_address: "str | None", device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_ipv4 yet"
        )

    def set_svi_ipv4_secondary(
        self, vlan_id: int, ipv4_address: "str | None", previous_ipv4_address: "str | None",
        device: Device, password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_ipv4_secondary yet"
        )

    def set_svi_ipv6(self, vlan_id: int, ipv6_address: "str | None", device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_ipv6 yet"
        )

    def set_svi_acl(
        self, vlan_id: int, direction: str, acl_name: "str | None", device: Device, password: str,
        *, current_acl_name: "str | None" = None,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_acl yet"
        )

    def list_acl_names(self, device: Device, password: str) -> list[str]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement list_acl_names yet"
        )

    def list_acls(self, device: Device, password: str) -> list[dict]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement list_acls yet"
        )


    def formatear_regla_acl(self, rule: dict) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement formatear_regla_acl yet"
        )

    def create_or_update_acl(self, name: str, rule_lines: list[str], device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement create_or_update_acl yet"
        )

    def remove_acl_rules(self, name: str, rule_lines: list[str], device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement remove_acl_rules yet"
        )

    def delete_acl(self, name: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement delete_acl yet"
        )

    def set_svi_dhcp_relay(
        self, vlan_id: int, servers: list[str], device: Device, password: str,
    ) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_svi_dhcp_relay yet"
        )

    def get_svis(self, device: Device, password: str) -> list[SVI]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_svis yet"
        )

    def get_global_config(self, device: Device, password: str) -> "GlobalConfig":
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_global_config yet"
        )

    def set_hostname(self, hostname: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_hostname yet"
        )

    def set_snmp(self, cambios: dict, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_snmp yet"
        )

    def get_arp_table(self, device: Device, password: str) -> "list[dict]":
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_arp_table yet"
        )

    def get_mac_table(self, device: Device, password: str) -> "list[dict]":
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_mac_table yet"
        )

    def search_mac_table(self, pattern: str, device: Device, password: str) -> "list[dict]":
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement search_mac_table yet"
        )

    def get_log_buffer(self, device: Device, password: str) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_log_buffer yet"
        )

    def add_log_server(self, server: str, level: "str | None", device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_log_server yet"
        )

    def remove_log_server(self, server: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement remove_log_server yet"
        )

    def set_route(self, destination: str, next_hop: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_route yet"
        )

    def remove_route(self, destination: str, next_hop: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement remove_route yet"
        )

    def add_ntp_server(self, server: str, prefer: bool, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_ntp_server yet"
        )

    def remove_ntp_server(self, server: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement remove_ntp_server yet"
        )

    def add_dns_server(self, server: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_dns_server yet"
        )

    def remove_dns_server(self, server: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement remove_dns_server yet"
        )

    def set_dns_domain(self, domain: str, device: Device, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement set_dns_domain yet"
        )

    @staticmethod
    def _red_y_mascara(cidr: str) -> tuple[str, str]:
        red = ipaddress.ip_network(cidr, strict=False)
        return str(red.network_address), str(red.netmask)

    @staticmethod
    def _red_y_wildcard(cidr: str) -> tuple[str, str]:
        red = ipaddress.ip_network(cidr, strict=False)
        return str(red.network_address), str(red.hostmask)

    @staticmethod
    def _combinar_resultados(resultados: list[dict]) -> dict:
        if not resultados:
            return {"rc": 0, "stdout": "", "stderr": "", "success": True, "changed": False}
        return {
            "rc": max(r.get("rc", 0) for r in resultados),
            "stdout": "\n".join(r.get("stdout", "") for r in resultados),
            "stderr": "\n".join(r.get("stderr", "") for r in resultados if r.get("stderr")),
            "success": all(r.get("success") for r in resultados),
        }
