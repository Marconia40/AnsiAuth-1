from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.composition import svi_repository
from app.models.svi import SVI
from app.models.management_vlan import detectar_vlan_gestion

from tests._puerto_fakes import get_or_create_device


def _svi(vlan, primary=None, secondary=None):
    return SimpleNamespace(vlan_id=vlan, ipv4_address=primary, ipv4_address_secondary=secondary)


def test_exact_primary_address_wins():
    svis = [_svi(10, "10.0.0.1/24"), _svi(156, "10.237.61.126/22")]
    assert detectar_vlan_gestion("10.237.61.126", svis) == 156


def test_exact_secondary_address():
    svis = [_svi(10, "10.0.0.1/24"), _svi(20, "10.234.20.1/24", ["10.237.61.126/22"])]
    assert detectar_vlan_gestion("10.237.61.126", svis) == 20


def test_exact_match_beats_a_more_specific_containing_subnet():
    svis = [_svi(30, "10.237.61.1/30"), _svi(156, "10.237.61.126/22")]
    assert detectar_vlan_gestion("10.237.61.126", svis) == 156


def test_vip_falls_back_to_the_most_specific_containing_subnet():
    svis = [_svi(100, "10.237.60.2/16"), _svi(156, "10.237.61.2/24"), _svi(10, "10.0.0.1/24")]
    assert detectar_vlan_gestion("10.237.61.1", svis) == 156


def test_equal_prefix_tie_picks_the_lowest_vlan():
    svis = [_svi(200, "10.237.61.2/24"), _svi(150, "10.237.61.3/24")]
    assert detectar_vlan_gestion("10.237.61.1", svis) == 150


@pytest.mark.parametrize("host", ["core-sw.example.org", "", "999.1.1.1", "2001:db8::1"])
def test_host_that_is_not_an_ipv4_address_gives_none(host):
    assert detectar_vlan_gestion(host, [_svi(156, "10.237.61.126/22")]) is None


def test_no_svi_covers_the_host():
    assert detectar_vlan_gestion("192.0.2.10", [_svi(10, "10.0.0.1/24"), _svi(1)]) is None


def test_no_svis_and_garbage_addresses_are_ignored():
    assert detectar_vlan_gestion("192.0.2.10", []) is None
    assert detectar_vlan_gestion("192.0.2.10", [_svi(10, "not-an-ip"), _svi(20, "", [""])]) is None


_DEVICE = "mgmt_vlan_dev"


@pytest.fixture
def device():
    return get_or_create_device(_DEVICE, site_name="Mgmt VLAN Test Site", host="192.0.2.77")


def test_ports_and_svis_list_expose_management_vlan(admin_client, device):
    svi_repository.add(SVI(vlan_id=10, device=_DEVICE, ipv4_address="10.0.0.1/24"))
    svi_repository.add(SVI(vlan_id=77, device=_DEVICE, ipv4_address="192.0.2.77/24"))

    ports = admin_client.get(f"/api/v1/devices/{_DEVICE}/ports/").json()["data"]["data"]
    svis = admin_client.get(f"/api/v1/devices/{_DEVICE}/svis/").json()["data"]["data"]

    assert ports["management_vlan"] == 77
    assert svis["management_vlan"] == 77


def test_management_vlan_is_null_when_no_svi_matches(admin_client):
    other = get_or_create_device("mgmt_vlan_dev2", site_name="Mgmt VLAN Test Site", host="203.0.113.5")
    svi_repository.add(SVI(vlan_id=10, device=other.name, ipv4_address="10.0.0.1/24"))

    ports = admin_client.get(f"/api/v1/devices/{other.name}/ports/").json()["data"]["data"]
    assert ports["management_vlan"] is None
