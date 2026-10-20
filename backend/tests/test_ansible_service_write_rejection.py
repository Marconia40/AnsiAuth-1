from __future__ import annotations

from app.services import ansible_service

_real_run_playbook = ansible_service.run_playbook


class _FakeRunnerResult:
    def __init__(self, rc: int, stdout: str, stderr: str = ""):
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.status = "successful" if rc == 0 else "failed"
        self.events = []


def _patch_runner(monkeypatch, result: _FakeRunnerResult):
    monkeypatch.setattr(ansible_service._runner, "run", lambda **kwargs: result)
    from app.composition import redis_coordinator
    import contextlib
    monkeypatch.setattr(redis_coordinator, "adquirir_slot", lambda: contextlib.nullcontext())


def test_huawei_rejection_forces_rc_1_despite_task_reporting_ok(monkeypatch):
    transcript = (
        "[swhw02]interface GE0/0/43\n"
        "                  ^\n"
        "Error: Wrong parameter found at '^' position.\n"
        "[swhw02]"
    )
    _patch_runner(monkeypatch, _FakeRunnerResult(rc=0, stdout=transcript))

    result = _real_run_playbook(
        playbook="vendors/huawei/run.yml",
        extravars={"command_block": "system-view\ninterface GE0/0/43\n..."},
        inventory="swhw02 ansible_host=10.237.61.56",
        device="swhw02",
        vendor="huawei_vrp",
    )

    assert result["rc"] == 1


def test_cisco_rejection_forces_rc_1_despite_task_reporting_ok(monkeypatch):
    transcript = (
        "router#show vlam brief\n"
        "         ^\n"
        "% Invalid input detected at '^' marker.\n"
        "router#"
    )
    _patch_runner(monkeypatch, _FakeRunnerResult(rc=0, stdout=transcript))

    result = _real_run_playbook(
        playbook="vendors/cisco/run.yml",
        extravars={"commands": ["show vlam brief"]},
        inventory="cisco01 ansible_host=192.0.2.10",
        device="cisco01",
        vendor="cisco_ios",
    )

    assert result["rc"] == 1


def test_genuinely_successful_write_keeps_rc_0(monkeypatch):
    transcript = "[swhw02-GigabitEthernet0/0/43]port link-type trunk\n[swhw02-GigabitEthernet0/0/43]"
    _patch_runner(monkeypatch, _FakeRunnerResult(rc=0, stdout=transcript))

    result = _real_run_playbook(
        playbook="vendors/huawei/run.yml",
        extravars={"command_block": "system-view\ninterface GigabitEthernet0/0/43\n..."},
        inventory="swhw02 ansible_host=10.237.61.56",
        device="swhw02",
        vendor="huawei_vrp",
    )

    assert result["rc"] == 0
    assert result["stdout"] == transcript


def test_no_vendor_passed_does_not_crash(monkeypatch):
    transcript = "Error: something went wrong\ndevice#"
    _patch_runner(monkeypatch, _FakeRunnerResult(rc=0, stdout=transcript))

    result = _real_run_playbook(
        playbook="vendors/huawei/run.yml",
        extravars={"command_block": "..."},
        inventory="somedevice ansible_host=192.0.2.1",
        device="somedevice",
    )

    assert result["rc"] == 1
