from __future__ import annotations

from app.services.vendors.huawei.driver import HuaweiVendor


def test_primary_incluye_la_y():
    comandos = HuaweiVendor()._cargar_comandos()["set_trunk_mode"]
    assert "y" in comandos["primary"]["block"]


def test_alternativa_sin_y_para_devices_que_la_rechazan():
    comandos = HuaweiVendor()._cargar_comandos()["set_trunk_mode"]
    alternativas = comandos["alternatives"]
    triggers = [a["triggered_by_error"] for a in alternativas]
    assert any("Unrecognized command" in t and r"\]y" in t for t in triggers)
    alt = next(a for a in alternativas if r"\]y" in a["triggered_by_error"])
    assert "y" not in alt["block"]
    assert [l for l in comandos["primary"]["block"] if l != "y"] == alt["block"]


def test_regex_alternativa_matchea_el_error_real_observado():
    import re
    comandos = HuaweiVendor()._cargar_comandos()["set_trunk_mode"]
    alt = next(a for a in comandos["alternatives"] if r"\]y" in a["triggered_by_error"])
    error_real = (
        "[swhw01-GigabitEthernet0/0/2]port link-type trunk\r\n"
        "Warning: This command will delete VLANs on this port. Continue?[Y/N]:n\r\n"
        "[swhw01-GigabitEthernet0/0/2]undo port trunk allow-pass vlan all\r\n"
        "                                       ^\r\n"
        "Error: Unrecognized command found at '^' position.\r\n"
        "[swhw01-GigabitEthernet0/0/2]"
    )
    error_y_rechazada = (
        "[*HUAWEI-GE1/0/2]port link-type trunk\r\n"
        "Warning: If this command is executed successfully, VLANs allowed "
        "to pass through this interface will be deleted.\r\n"
        "[*HUAWEI-GE1/0/2]y\r\n"
        "                 ^\r\n"
        "Error: Unrecognized command found at '^' position.\r\n"
        "[*HUAWEI-GE1/0/2]"
    )
    assert not re.search(alt["triggered_by_error"], error_real)
    assert re.search(alt["triggered_by_error"], error_y_rechazada)


def test_alternativas_de_interface_y_commit_tambien_incluyen_la_y():
    comandos = HuaweiVendor()._cargar_comandos()["set_trunk_mode"]
    for alt in comandos["alternatives"]:
        if r"\]y" in alt["triggered_by_error"]:
            continue
        assert "y" in alt["block"], alt["triggered_by_error"]
