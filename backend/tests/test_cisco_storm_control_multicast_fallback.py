from __future__ import annotations

import re

from app.services.vendors.cisco.driver import CiscoVendor


def _comandos():
    return CiscoVendor()._cargar_comandos()["set_storm_control"]


def test_primary_incluye_include_multicast():
    comandos = _comandos()
    assert "storm-control broadcast include multicast" in comandos["enabled"]["primary"]["lines"]


def test_alternativa_enabled_manda_multicast_por_separado():
    comandos = _comandos()
    alt = comandos["enabled"]["alternatives"][0]
    assert "storm-control broadcast include multicast" not in alt["lines"]
    assert "storm-control multicast level {threshold}" in alt["lines"]
    assert "storm-control broadcast level {threshold}" in alt["lines"]
    assert alt["repeat"] == comandos["enabled"]["primary"]["repeat"]


def test_alternativa_disabled_manda_multicast_por_separado():
    comandos = _comandos()
    assert "no storm-control broadcast include multicast" in comandos["disabled"]["primary"]["lines"]
    alt = comandos["disabled"]["alternatives"][0]
    assert "no storm-control broadcast include multicast" not in alt["lines"]
    assert "no storm-control multicast level" in alt["lines"]
    assert "no storm-control broadcast level" in alt["lines"]


def test_regex_alternativa_matchea_el_error_real_observado():
    comandos = _comandos()
    alt = comandos["enabled"]["alternatives"][0]
    error_real = (
        "swcs01(config)#interface Gi1/0/1\r\n"
        "swcs01(config-if)#storm-control broadcast include multicast\r\n"
        "                                          ^\r\n"
        "% Invalid input detected at '^' marker.\r\n\r\n"
        "swcs01(config-if)#storm-control broadcast level 10.0\r\n"
        "swcs01(config-if)#storm-control action trap\r\n"
        "swcs01(config-if)#end\r\n"
        "swcs01#quit"
    )
    assert re.search(alt["triggered_by_error"], error_real)


def test_regex_alternativa_no_matchea_otro_error_no_relacionado():
    comandos = _comandos()
    alt = comandos["enabled"]["alternatives"][0]
    error_no_relacionado = (
        "swcs01(config-if)#storm-control broadcast level 999\r\n"
        "                                                 ^\r\n"
        "% Invalid input detected at '^' marker.\r\n"
    )
    assert not re.search(alt["triggered_by_error"], error_no_relacionado)
