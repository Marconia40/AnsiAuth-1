from __future__ import annotations

import re

from app.services.parsers._common import strip_ansi

_IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


_CISCO_ARP_RE = re.compile(r"^Internet\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
_CISCO_MAC_RE = re.compile(r"^\s*(\S+)\s+(\S+\.\S+\.\S+)\s+(.+?)\s+(\S+)\s*$")


def parse_cisco_arp(raw: str) -> list[dict]:
    entradas = []
    for linea in raw.splitlines():
        m = _CISCO_ARP_RE.match(strip_ansi(linea).rstrip())
        if m:
            ip, age, mac, tipo, interface = m.groups()
            entradas.append({"ip": ip, "mac": mac, "age": age, "type": tipo, "interface": interface, "vlan": None})
    return entradas


def parse_cisco_mac(raw: str) -> list[dict]:
    entradas = []
    for linea in raw.splitlines():
        m = _CISCO_MAC_RE.match(strip_ansi(linea).rstrip())
        if m:
            vlan, mac, tipo, interface = m.groups()
            entradas.append({"mac": mac, "vlan": vlan, "type": tipo, "interface": interface})
    return entradas


_VRP_VLAN_CONTINUATION_RE = re.compile(r"^\s*(\d+)/")

_HUAWEI_MAC_RE = re.compile(r"^(\S{4}-\S{4}-\S{4})\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+\S+)?\s*$")


def parse_huawei_arp(raw: str) -> list[dict]:
    lineas = [strip_ansi(l).rstrip() for l in raw.splitlines()]
    entradas = []
    i, n = 0, len(lineas)
    while i < n:
        tokens = lineas[i].split()
        if len(tokens) == 5 and _IP_RE.match(tokens[0]):
            ip, mac, age, tipo, interface = tokens
            vlan = None
            if i + 1 < n:
                m = _VRP_VLAN_CONTINUATION_RE.match(lineas[i + 1])
                if m:
                    vlan = m.group(1)
                    i += 1
            entradas.append({"ip": ip, "mac": mac, "age": age, "type": tipo, "interface": interface, "vlan": vlan})
        i += 1
    return entradas


def parse_huawei_mac(raw: str) -> list[dict]:
    entradas = []
    for linea in raw.splitlines():
        m = _HUAWEI_MAC_RE.match(strip_ansi(linea).rstrip())
        if m:
            mac, vlan_vsi_bd, interface, tipo = m.groups()
            entradas.append({"mac": mac, "vlan": vlan_vsi_bd.split("/")[0], "type": tipo, "interface": interface})
    return entradas
