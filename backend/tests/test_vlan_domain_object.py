import pytest

from app.models.vlan import VLAN


def test_vlan_id_out_of_range_raises_on_construction():
    with pytest.raises(ValueError):
        VLAN(vlan_id=0)
    with pytest.raises(ValueError):
        VLAN(vlan_id=4095)


def test_vlan_reserved_id_raises_on_construction():
    for reserved in (1, 1002, 1003, 1004, 1005):
        with pytest.raises(ValueError):
            VLAN(vlan_id=reserved)


def test_vlan_construction_never_validates_name():
    vlan = VLAN(vlan_id=10, name="Guest Network")
    assert vlan.name == "Guest Network"


def test_vlan_without_name_is_valid_for_delete():
    vlan = VLAN(vlan_id=10)
    assert vlan.name == ""


def test_validate_name_rejects_bad_format():
    vlan = VLAN(vlan_id=10, name="Guest Network")
    with pytest.raises(ValueError):
        vlan.validar()


def test_validate_name_accepts_good_format():
    vlan = VLAN(vlan_id=10, name="Guest-Network")
    vlan.validar()


def test_validar_skips_name_check_when_eliminar():
    vlan = VLAN(vlan_id=10, eliminar=True)
    vlan.validar()
