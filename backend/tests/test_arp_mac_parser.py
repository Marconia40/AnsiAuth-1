from __future__ import annotations

from app.services.parsers.arp_mac_parser import parse_huawei_mac


def test_parse_huawei_mac_confirmed_format_sin_age():
    raw = (
        "MAC Address    VLAN/VSI/BD   Learned-From        Type\n"
        "-------------------------------------------------------------------------------\n"
        "02a0-b100-0003 156/-/-                           GE0/0/48            dynamic\n"
        "-------------------------------------------------------------------------------\n"
        "Total items displayed = 1\n"
    )
    rows = parse_huawei_mac(raw)
    assert len(rows) == 1
    assert rows[0] == {
        "mac": "02a0-b100-0003", "vlan": "156", "type": "dynamic", "interface": "GE0/0/48",
    }


def test_parse_huawei_mac_with_trailing_age_column():
    raw = (
        "Flags: * - Backup  \n"
        "       # - forwarding logical interface, operations cannot be performed based \n"
        "           on the interface.\n"
        "BD   : bridge-domain   Age : dynamic MAC learned time in seconds\n"
        "-------------------------------------------------------------------------------\n"
        "MAC Address    VLAN/BD       Learned-From        Type                Age\n"
        "-------------------------------------------------------------------------------\n"
        "02a0-b100-0004 1/-           Eth-Trunk4          dynamic                 27\n"
        "02a0-b100-0005 999/-         10GE6/0/31          dynamic                  3\n"
        "02a0-b100-0001 999/-         10GE6/0/31          dynamic                  2\n"
        "-------------------------------------------------------------------------------\n"
        "Total items: 3\n"
    )
    rows = parse_huawei_mac(raw)
    assert len(rows) == 3
    assert rows[0] == {
        "mac": "02a0-b100-0004", "vlan": "1", "type": "dynamic", "interface": "Eth-Trunk4",
    }
    assert rows[1]["interface"] == "10GE6/0/31"
    assert rows[2]["mac"] == "02a0-b100-0001"


def test_parse_huawei_mac_empty_input():
    assert parse_huawei_mac("") == []
