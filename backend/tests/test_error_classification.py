from app.services.orquestador import Orquestador, _resumir_error


def _clasificar(resultado: dict):
    orq = Orquestador(None, None, None, None, None)
    return orq._clasificar_error(resultado)


def test_auth_error_no_retry_and_summary():
    decision = _clasificar({"stderr": "% Authentication failure", "stdout": ""})
    assert decision.should_retry is False
    assert decision.classification == "permanent"
    assert decision.categoria == "auth"
    assert "credentials" in _resumir_error(decision)


def test_syntax_error_no_retry_and_summary():
    decision = _clasificar({"stderr": "% Invalid input detected at '^' marker.", "stdout": ""})
    assert decision.should_retry is False
    assert decision.categoria == "syntax"
    assert "rejected" in _resumir_error(decision)


def test_conflict_error_no_retry_and_summary():
    decision = _clasificar({"stderr": "", "stdout": "VLAN already exists on this device"})
    assert decision.should_retry is False
    assert decision.categoria == "conflict"
    assert "conflicts" in _resumir_error(decision)


def test_connectivity_error_retries_and_summary():
    decision = _clasificar({"stderr": "Connection reset by peer", "stdout": ""})
    assert decision.should_retry is True
    assert decision.classification == "transient"
    assert decision.categoria == "connectivity"
    assert "connectivity" in _resumir_error(decision)


def test_session_limit_error_retries_and_summary():
    decision = _clasificar({"stderr": "Error: too many sessions", "stdout": ""})
    assert decision.should_retry is True
    assert decision.categoria == "session_limit"
    assert "SSH sessions" in _resumir_error(decision)


def test_read_reliability_error_retries_and_summary():
    decision = _clasificar({"stderr": "possible read desync", "stdout": ""})
    assert decision.should_retry is True
    assert decision.categoria == "read_reliability"
    assert "read reliably" in _resumir_error(decision)


def test_ansible_rc_transient_has_no_categoria_but_gets_generic_summary():
    decision = _clasificar({"rc": 4, "stderr": "", "stdout": ""})
    assert decision.should_retry is True
    assert decision.classification == "transient"
    assert decision.categoria is None
    assert _resumir_error(decision) == "A transient connectivity issue occurred and retries were exhausted."


def test_unknown_error_gets_generic_summary():
    decision = _clasificar({"stderr": "some totally unrecognized gibberish", "stdout": ""})
    assert decision.should_retry is True
    assert decision.classification == "unknown"
    assert decision.categoria is None
    assert _resumir_error(decision) == (
        "The device gave an unfamiliar response — could not determine the exact cause."
    )


def test_ansible_unreachable_with_auth_failure_is_permanent():
    decision = _clasificar({
        "rc": 4, "stderr": "",
        "stdout": "ssh connection failed: Failed to authenticate public key: Authentication failed.",
    })
    assert decision.should_retry is False
    assert decision.classification == "permanent"
    assert decision.categoria == "auth"


def test_ansible_unreachable_with_connectivity_text_keeps_categoria():
    decision = _clasificar({"rc": 4, "stderr": "", "stdout": "Connection timed out"})
    assert decision.should_retry is True
    assert decision.classification == "transient"
    assert decision.categoria == "connectivity"


def test_host_key_mismatch_openssh_no_retry_and_summary():
    decision = _clasificar({"rc": 255, "stdout": "", "stderr": (
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
        "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
        "Host key for fakesw has changed and you have requested strict checking.\n"
        "Host key verification failed.\n"
    )})
    assert decision.should_retry is False
    assert decision.categoria == "host_key"
    assert "host key" in _resumir_error(decision)


def test_host_key_mismatch_ansible_no_retry():
    decision = _clasificar({"rc": 2, "stdout": "host key mismatch for fakesw", "stderr": ""})
    assert decision.should_retry is False
    assert decision.categoria == "host_key"
