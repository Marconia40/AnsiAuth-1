from app.services.parsers.port_parser import (
    parse_vrp_interface_brief,
    parse_vrp_interface_description,
    parse_vrp_port_vlan,
    parse_vrp_ports,
)


BRIEF_SAMPLE = """\
PHY: Physical
*down: administratively down
^down: standby
(l): loopback
(s): spoofing
(b): BFD down
(e): ETHOAM down
(d): Dampening Suppressed
(p): port alarm down
(dl): DLDP down
(lb): LBDT down
(ld): link-flap down
(ng): NGE error down
InUti/OutUti: input utility/output utility
Interface                   PHY     Protocol  InUti OutUti   inErrors  outErrors
GigabitEthernet0/0/1        up      up        0.01%  0.01%        0        0
GigabitEthernet0/0/2        *down   down      0%     0%           0        0
GigabitEthernet0/0/3        down    down      0%     0%           0        0
GigabitEthernet0/0/4        up      up(s)     0%     0%           0        0
Vlanif1                     up      up        --     --           0        0
NULL0                       up      up(s)     --     --           0        0
Eth-Trunk1                  up      up        0%     0%           0        0
Sip9/0/0                    up      down      --     --           0        0
"""


def test_brief_filters_pseudo_interfaces():
    rows = parse_vrp_interface_brief(BRIEF_SAMPLE)
    assert "Vlanif1" not in rows
    assert "NULL0" not in rows
    assert "Sip9/0/0" not in rows
    assert set(rows.keys()) == {
        "GE0/0/1",
        "GE0/0/2",
        "GE0/0/3",
        "GE0/0/4",
        "Eth-Trunk1",
    }


def test_brief_admin_state_mapping():
    rows = parse_vrp_interface_brief(BRIEF_SAMPLE)
    assert rows["GE0/0/1"].admin_up is True
    assert rows["GE0/0/2"].admin_up is False
    assert rows["GE0/0/3"].admin_up is True
    assert rows["GE0/0/4"].admin_up is True


def test_brief_operational_state_mapping():
    rows = parse_vrp_interface_brief(BRIEF_SAMPLE)
    assert rows["GE0/0/1"].operational_up is True
    assert rows["GE0/0/2"].operational_up is False
    assert rows["GE0/0/3"].operational_up is False
    assert rows["GE0/0/4"].operational_up is True


def test_brief_empty_input():
    assert parse_vrp_interface_brief("") == {}


DESCRIPTION_SAMPLE = """\
PHY: Physical
*down: administratively down
^down: standby
(l): loopback
(s): spoofing
Interface                  PHY      Protocol Description
GigabitEthernet0/0/1       up       up       Workstation01
GigabitEthernet0/0/2       *down    down     Reserved port for printer
GigabitEthernet0/0/3       up       up
GigabitEthernet0/0/4       up       up       multi word description here
Eth-Trunk1                 up       up       LAG to core
"""


def test_descriptions_extracted_with_spaces():
    rows = parse_vrp_interface_description(DESCRIPTION_SAMPLE)
    assert rows["GE0/0/1"] == "Workstation01"
    assert rows["GE0/0/2"] == "Reserved port for printer"
    assert rows["GE0/0/4"] == "multi word description here"


def test_empty_description_becomes_none():
    rows = parse_vrp_interface_description(DESCRIPTION_SAMPLE)
    assert rows["GE0/0/3"] is None


PORT_VLAN_SAMPLE = """\
Port                    Link Type    PVID  Trunk VLAN List
-------------------------------------------------------------------
GigabitEthernet0/0/1    access       10    -
GigabitEthernet0/0/2    trunk        1     2 to 4094
GigabitEthernet0/0/3    hybrid       1     1 untagged, 100 tagged
GigabitEthernet0/0/4    trunk        99    10, 20, 30 to 32
GigabitEthernet0/0/5    access       1     -
GigabitEthernet0/0/6    trunk        50    50 400
GigabitEthernet0/0/7    trunk        1     10 20 30 to 32
Eth-Trunk1              trunk        1     10 20
"""


def test_port_vlan_access_mode():
    rows = parse_vrp_port_vlan(PORT_VLAN_SAMPLE)
    row = rows["GE0/0/1"]
    assert row.mode == "access"
    assert row.access_vlan == 10
    assert row.allowed_vlans is None


def test_port_vlan_trunk_with_range():
    rows = parse_vrp_port_vlan(PORT_VLAN_SAMPLE)
    row = rows["GE0/0/2"]
    assert row.mode == "trunk"
    assert row.access_vlan == 1
    assert row.allowed_vlans is not None
    assert row.allowed_vlans[0] == 2
    assert row.allowed_vlans[-1] == 4094
    assert len(row.allowed_vlans) == 4093


def test_port_vlan_hybrid_normalized_to_unknown():
    rows = parse_vrp_port_vlan(PORT_VLAN_SAMPLE)
    row = rows["GE0/0/3"]
    assert row.mode == "unknown"
    assert row.access_vlan == 1
    assert row.allowed_vlans is None


def test_port_vlan_trunk_mixed_list_and_range():
    rows = parse_vrp_port_vlan(PORT_VLAN_SAMPLE)
    row = rows["GE0/0/4"]
    assert row.mode == "trunk"
    assert row.access_vlan == 99
    assert row.allowed_vlans == [10, 20, 30, 31, 32]


def test_port_vlan_trunk_space_separated():
    rows = parse_vrp_port_vlan(PORT_VLAN_SAMPLE)
    row = rows["GE0/0/6"]
    assert row.mode == "trunk"
    assert row.access_vlan == 50
    assert row.allowed_vlans == [50, 400]


def test_port_vlan_trunk_mixed_space_and_range():
    rows = parse_vrp_port_vlan(PORT_VLAN_SAMPLE)
    row = rows["GE0/0/7"]
    assert row.mode == "trunk"
    assert row.access_vlan == 1
    assert row.allowed_vlans == [10, 20, 30, 31, 32]


def test_port_vlan_empty_input():
    assert parse_vrp_port_vlan("") == {}


PORT_VLAN_WITH_DESCRIPTION_SAMPLE = """\
Port                    Link Type    PVID  Trunk VLAN List                      Port Description
---------------------------------------------------------------------------------------------------------------
Eth-Trunk2              trunk         520  52 90 102 118-119 138 156 301 381    trunk a rou-fcm2 - Eth-Trunk2
                                           397 520 900
Vlanif10                trunk           1  10 20 30                            SVI, still filtered
                                           40 50
10GE6/0/34              trunk         529  144 381                              Trunk rou-planeamiento1 TGE1/1/
                                                                                3
10GE6/0/35              trunk         599  16 38 45 50-51 53 57 59 82 96 107    Trunk rou-trejo1 XGE0/0/24
                                           124 135 138 155-157 195 316 338 345
                                           353 361 381-382 596 599 900
10GE6/0/43              trunk         531  144 381 531                          rou-dui2 XGE0/0/1
10GE6/0/47              access          1  --
"""


def test_port_vlan_description_digits_are_not_phantom_vlans():
    rows = parse_vrp_port_vlan(PORT_VLAN_WITH_DESCRIPTION_SAMPLE)
    row = rows["10GE6/0/43"]
    assert row.mode == "trunk"
    assert row.access_vlan == 531
    assert row.allowed_vlans == [144, 381, 531]


def test_port_vlan_wrapped_description_does_not_add_phantom_vlan():
    rows = parse_vrp_port_vlan(PORT_VLAN_WITH_DESCRIPTION_SAMPLE)
    row = rows["10GE6/0/34"]
    assert row.allowed_vlans == [144, 381]


def test_port_vlan_wrapped_trunk_list_is_merged_across_lines():
    rows = parse_vrp_port_vlan(PORT_VLAN_WITH_DESCRIPTION_SAMPLE)
    row = rows["10GE6/0/35"]
    assert row.allowed_vlans == [
        16, 38, 45, 50, 51, 53, 57, 59, 82, 96, 107,
        124, 135, 138, 155, 156, 157, 195, 316, 338, 345,
        353, 361, 381, 382, 596, 599, 900,
    ]


def test_port_vlan_continuation_after_filtered_pseudo_interface_is_ignored():
    rows = parse_vrp_port_vlan(PORT_VLAN_WITH_DESCRIPTION_SAMPLE)
    assert "Vlanif10" not in rows
    row = rows["10GE6/0/34"]
    assert row.allowed_vlans == [144, 381]


def test_port_vlan_eth_trunk_is_included_not_filtered():
    rows = parse_vrp_port_vlan(PORT_VLAN_WITH_DESCRIPTION_SAMPLE)
    row = rows["Eth-Trunk2"]
    assert row.mode == "trunk"
    assert row.access_vlan == 520
    assert row.allowed_vlans == [52, 90, 102, 118, 119, 138, 156, 301, 381, 397, 520, 900]


def test_combined_parser_merges_three_sources():
    ports = parse_vrp_ports(BRIEF_SAMPLE, DESCRIPTION_SAMPLE, PORT_VLAN_SAMPLE)
    by_name = {p.interface: p for p in ports}

    assert "Vlanif1" not in by_name
    assert "NULL0" not in by_name

    assert [p.interface for p in ports] == sorted(p.interface for p in ports)

    g1 = by_name["GE0/0/1"]
    assert g1.description == "Workstation01"
    assert g1.admin_up is True
    assert g1.operational_up is True
    assert g1.mode == "access"
    assert g1.access_vlan == 10
    assert g1.allowed_vlans is None

    g2 = by_name["GE0/0/2"]
    assert g2.description == "Reserved port for printer"
    assert g2.admin_up is False
    assert g2.operational_up is False

    trunk = by_name["Eth-Trunk1"]
    assert trunk.kind == "aggregate"
    assert trunk.description == "LAG to core"
    assert trunk.mode == "trunk"
    assert trunk.allowed_vlans == [10, 20]

    assert g1.kind == "physical"
    assert g2.kind == "physical"

    for p in ports:
        assert p.poe_enabled is None
        assert p.speed is None
        assert p.duplex is None


def test_combined_parser_tolerates_missing_sources():
    ports = parse_vrp_ports("", "", PORT_VLAN_SAMPLE)
    by_name = {p.interface: p for p in ports}
    g1 = by_name["GE0/0/1"]
    assert g1.admin_up is None
    assert g1.operational_up is None
    assert g1.description is None
    assert g1.mode == "access"
    assert g1.access_vlan == 10


def test_combined_parser_tolerates_empty_everywhere():
    assert parse_vrp_ports("", "", "") == []


def test_combined_parser_handles_ports_only_in_one_source():
    brief_only = """\
Interface                   PHY     Protocol  InUti OutUti   inErrors  outErrors
GigabitEthernet0/0/99       up      up        0%     0%           0        0
"""
    ports = parse_vrp_ports(brief_only, "", "")
    assert len(ports) == 1
    assert ports[0].interface == "GE0/0/99"
    assert ports[0].mode == "unknown"
    assert ports[0].admin_up is True
    assert ports[0].operational_up is True
