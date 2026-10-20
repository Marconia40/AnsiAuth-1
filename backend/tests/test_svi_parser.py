from app.services.parsers.svi_parser import HuaweiSVIParser

_BRIEF = """\
Interface                   IP Address/Mask      Physical   Protocol
Vlanif156                   10.237.61.190/22      up         up
Vlanif399                   10.243.64.1/19         up         up
Vlanif500                   10.239.2.8/24          up         up
Vlanif502                   10.239.0.153/29        up         up
"""


def _config(*blocks: str) -> str:
    return "\n".join(blocks)


def test_acl_direction_before_acl_confirmed_swhw01_order():
    config = _config("""\
#
interface Vlanif156
 ip address 10.237.61.190 255.255.252.0
 traffic-filter inbound acl 3002
#
""")
    svis = HuaweiSVIParser.parse_svis(config, _BRIEF)
    svi = next(s for s in svis if s.vlan_id == 156)
    assert svi.acl_in == "3002"
    assert svi.acl_out is None


def test_acl_direction_before_acl_named_confirmed_swhw01_order():
    config = _config("""\
#
interface Vlanif156
 traffic-filter outbound acl name test-acl
#
""")
    svis = HuaweiSVIParser.parse_svis(config, _BRIEF)
    svi = next(s for s in svis if s.vlan_id == 156)
    assert svi.acl_out == "test-acl"
    assert svi.acl_in is None


def test_acl_direction_after_target_confirmed_swhw03_order():
    config = _config("""\
#
interface Vlanif502
 traffic-filter acl 3999 outbound
#
""")
    svis = HuaweiSVIParser.parse_svis(config, _BRIEF)
    svi = next(s for s in svis if s.vlan_id == 502)
    assert svi.acl_out == "3999"
    assert svi.acl_in is None


def test_acl_direction_after_target_named_confirmed_swhw03_order():
    config = _config("""\
#
interface Vlanif399
 traffic-filter acl wifi-publico inbound
 traffic-filter acl 3999 outbound
#
""")
    svis = HuaweiSVIParser.parse_svis(config, _BRIEF)
    svi = next(s for s in svis if s.vlan_id == 399)
    assert svi.acl_in == "wifi-publico"
    assert svi.acl_out == "3999"


def test_no_acl_line_leaves_both_none():
    config = _config("""\
#
interface Vlanif500
 ip address 10.239.2.8 255.255.255.0
#
""")
    svis = HuaweiSVIParser.parse_svis(config, _BRIEF)
    svi = next(s for s in svis if s.vlan_id == 500)
    assert svi.acl_in is None
    assert svi.acl_out is None
