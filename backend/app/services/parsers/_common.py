from __future__ import annotations

import re

ANSI_ESCAPE = re.compile(r"\x1B\[[0-9;]*m")


def strip_ansi(line: str) -> str:
    return ANSI_ESCAPE.sub("", line)


def strip_known_preamble(text: str, patterns: "list[str]", separador: "str | None" = None) -> str:
    lineas = text.splitlines()
    compilados = [re.compile(p) for p in patterns]
    while lineas and (
        lineas[0].strip() == ""
        or (separador is not None and lineas[0].strip() == separador)
        or any(p.match(lineas[0]) for p in compilados)
    ):
        lineas.pop(0)
    return "\n".join(lineas)


_UPTIME_RE = re.compile(r"uptime is ([^\r\n]+)")
_VERSION_SCAN_LINES = 5
_VERSION_STRING_RE = re.compile(r"Version\s+([0-9][\w.]*)")
_CISCO_MODEL_RE = re.compile(r"^Model Number\s*:\s*(.+)$", re.MULTILINE)
_CISCO_SERIAL_RE = re.compile(r"^System Serial Number\s*:\s*(.+)$", re.MULTILINE)
_HUAWEI_MODEL_RE = re.compile(r"^HUAWEI\s+(\S+)", re.MULTILINE)


def parse_version_info(raw: str) -> dict:
    resultado = {"raw": raw, "software_version": None, "model": None, "serial_number": None, "uptime": None}
    if not raw:
        return resultado

    m = _UPTIME_RE.search(raw)
    if m:
        resultado["uptime"] = m.group(1).strip()

    primeras_lineas = "\n".join(raw.splitlines()[:_VERSION_SCAN_LINES])
    m = _VERSION_STRING_RE.search(primeras_lineas)
    if m:
        resultado["software_version"] = m.group(1)

    m = _CISCO_MODEL_RE.search(raw)
    if m:
        resultado["model"] = m.group(1).strip()
    else:
        m = _HUAWEI_MODEL_RE.search(raw)
        if m:
            resultado["model"] = m.group(1)

    m = _CISCO_SERIAL_RE.search(raw)
    if m:
        resultado["serial_number"] = m.group(1).strip()

    return resultado
