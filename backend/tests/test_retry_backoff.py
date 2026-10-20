import logging

import app.services.orquestador as orquestador_module
from app.composition import orquestador
from app.models.job import Job


def _make_fn(rc_sequence, transient_text="ssh timeout"):
    it = iter(rc_sequence)
    def fn():
        rc = next(it)
        return {"rc": rc, "stdout": transient_text if rc != 0 else "ok", "stderr": ""}
    return fn


def _job() -> Job:
    return Job(max_retries=10)


def test_delay_capped_at_max(monkeypatch):
    delays_recorded = []
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: delays_recorded.append(d))

    fn = _make_fn([1, 1, 1, 1])
    orquestador._ejecutar_con_retry(fn, _job(), "cap-test-device", max_retries=3, retry_base_delay=10.0)

    assert all(d <= 5.0 for d in delays_recorded), f"Uncapped delays: {delays_recorded}"
    assert len(delays_recorded) == 3


def test_normal_backoff_sequence(monkeypatch):
    delays_recorded = []
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: delays_recorded.append(d))

    fn = _make_fn([1, 1, 1, 1])
    orquestador._ejecutar_con_retry(fn, _job(), "backoff-test-device", max_retries=3, retry_base_delay=1.0)

    assert delays_recorded == [1.0, 2.0, 4.0]


def test_backoff_capped_at_5s_for_later_attempts(monkeypatch):
    delays_recorded = []
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: delays_recorded.append(d))

    fn = _make_fn([1, 1, 1, 1, 1, 1])
    orquestador._ejecutar_con_retry(fn, _job(), "cap5-test-device", max_retries=5, retry_base_delay=1.0)

    assert delays_recorded == [1.0, 2.0, 4.0, 5.0, 5.0]


def test_retry_count_returned_correctly(monkeypatch):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    fn = _make_fn([1, 1, 1, 0])
    _, retry_count = orquestador._ejecutar_con_retry(fn, _job(), "rc-test-device", max_retries=3, retry_base_delay=0.0)
    assert retry_count == 3


def test_zero_retries_on_immediate_success(monkeypatch):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    fn = _make_fn([0])
    _, retry_count = orquestador._ejecutar_con_retry(fn, _job(), "ok-test-device", max_retries=3, retry_base_delay=0.0)
    assert retry_count == 0


def test_permanent_error_no_sleep(monkeypatch):
    sleep_called = {"n": 0}
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: sleep_called.__setitem__("n", sleep_called["n"] + 1))

    fn = lambda: {"rc": 1, "stdout": "", "stderr": "syntax error"}
    orquestador._ejecutar_con_retry(fn, _job(), "perm-test-device", max_retries=3, retry_base_delay=1.0)

    assert sleep_called["n"] == 0


def test_permanent_error_called_once(monkeypatch):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return {"rc": 1, "stdout": "", "stderr": "permission denied"}

    orquestador._ejecutar_con_retry(fn, _job(), "perm2-test-device", max_retries=3, retry_base_delay=1.0)
    assert calls["n"] == 1


def test_retry_log_format(monkeypatch, caplog):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    fn = _make_fn([1, 1, 0])
    with caplog.at_level(logging.INFO, logger="app.services.orquestador"):
        orquestador._ejecutar_con_retry(fn, _job(), "log-test-device", max_retries=3, retry_base_delay=1.0)

    retry_lines = [r.message for r in caplog.records if "reintentando" in r.message]
    assert len(retry_lines) == 2
    assert "attempt=1/4" in retry_lines[0]
    assert "attempt=2/4" in retry_lines[1]
    assert "delay=1.00s" in retry_lines[0]
    assert "delay=2.00s" in retry_lines[1]


def test_exhausted_retries_log(monkeypatch, caplog):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    fn = _make_fn([1, 1, 1, 1])
    with caplog.at_level(logging.WARNING, logger="app.services.orquestador"):
        orquestador._ejecutar_con_retry(fn, _job(), "exhaust-test-device", max_retries=3, retry_base_delay=0.0)

    assert any("agotado" in r.message for r in caplog.records)


def test_no_exhausted_log_on_permanent(monkeypatch, caplog):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    fn = lambda: {"rc": 1, "stdout": "", "stderr": "authentication failure"}
    with caplog.at_level(logging.WARNING, logger="app.services.orquestador"):
        orquestador._ejecutar_con_retry(fn, _job(), "perm-log-test-device", max_retries=3, retry_base_delay=0.0)

    assert not any("agotado" in r.message for r in caplog.records)
    assert any("no reintenta" in r.message for r in caplog.records)


def test_no_exhausted_log_on_success(monkeypatch, caplog):
    monkeypatch.setattr(orquestador_module.time, "sleep", lambda d: None)

    fn = _make_fn([1, 1, 0])
    with caplog.at_level(logging.WARNING, logger="app.services.orquestador"):
        orquestador._ejecutar_con_retry(fn, _job(), "success-log-test-device", max_retries=3, retry_base_delay=0.0)

    assert not any("agotado" in r.message for r in caplog.records)
