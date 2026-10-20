from __future__ import annotations

import ipaddress
from typing import Iterable, Protocol


class _SviConDirecciones(Protocol):
    vlan_id: int
    ipv4_address: str | None
    ipv4_address_secondary: list[str] | None


def _interfaz(cidr: str | None) -> ipaddress.IPv4Interface | None:
    if not cidr:
        return None
    try:
        return ipaddress.IPv4Interface(cidr.strip())
    except ValueError:
        return None


def detectar_vlan_gestion(host: str, svis: Iterable[_SviConDirecciones]) -> int | None:
    try:
        ip = ipaddress.IPv4Address(host.strip())
    except ValueError:
        return None

    exacta: list[int] = []
    contiene: list[tuple[int, int]] = []
    for svi in svis:
        direcciones = [svi.ipv4_address, *(svi.ipv4_address_secondary or [])]
        for cidr in direcciones:
            iface = _interfaz(cidr)
            if iface is None:
                continue
            if iface.ip == ip:
                exacta.append(svi.vlan_id)
            elif ip in iface.network:
                contiene.append((iface.network.prefixlen, svi.vlan_id))

    if exacta:
        return min(exacta)
    if contiene:
        return min(contiene, key=lambda t: (-t[0], t[1]))[1]
    return None
