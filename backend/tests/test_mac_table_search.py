from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import ansible_service
from app.services.vendors.cisco.driver import CiscoVendor
from app.services.vendors.huawei.driver import HuaweiVendor


def _patch_ssh_paced(monkeypatch, fake_run):
    from app.services import ssh_direct_service

    monkeypatch.setattr(ssh_direct_service, "_SSH_DRAIN_DELAY_S", 0)

    def _run_ssh_paced(cmd, lines, env, terminador="quit"):
        return fake_run(cmd, "\n".join(lines) + f"\n{terminador}\n", True, True, None, env)

    monkeypatch.setattr(ssh_direct_service, "_run_ssh_paced", _run_ssh_paced)


class _FakeDevice:
    name = "cisco-01"
    host = "192.0.2.10"
    username = "admin"
    auth_method = "password"
    vendor = "cisco_ios"


def _make_run_result(rc: int, stdouts: list[str]) -> dict:
    return {"rc": rc, "stdout": "", "stderr": "", "stdouts": stdouts}


def _fake_clock_and_log_run(full_read_result: dict, *, clock: str = "19:00:57.437 AR Mon Sep 14 2026"):
    captured = {"all_commands": []}

    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        commands = extravars.get("commands")
        captured["all_commands"].append(commands)
        if commands == ["show logging | exclude CFGLOG_LOGGEDCMD"]:
            return full_read_result
        if commands == ["show clock"]:
            return _make_run_result(rc=0, stdouts=[clock])
        return captured.get("fallback_result", full_read_result)

    return _fake_run, captured


def test_get_log_buffer_happy_path_no_fallback(monkeypatch):
    fake_run, captured = _fake_clock_and_log_run(
        _make_run_result(rc=0, stdouts=["full log, no truncation"]),
    )
    monkeypatch.setattr(ansible_service, "run_playbook", fake_run)

    result = CiscoVendor().get_log_buffer(_FakeDevice(), "pw")

    assert result == "full log, no truncation"
    assert captured["all_commands"] == [["show logging | exclude CFGLOG_LOGGEDCMD"]]


def test_get_log_buffer_falls_back_on_session_drop(monkeypatch):
    from app.services.vendors.cisco import driver as driver_module

    fake_run, captured = _fake_clock_and_log_run(
        _make_run_result(rc=1, stdouts=["Feb 24 11:41:46: %SPANTREE-5-TOPOTRAP: Topology Cha"]),
    )
    captured["fallback_result"] = _make_run_result(rc=0, stdouts=["Sep 14 17:14:23: %SYS-5-CONFIG_I: ..."])
    monkeypatch.setattr(ansible_service, "run_playbook", fake_run)
    monkeypatch.setattr(driver_module, "_LOG_WINDOW_DAYS", 3)

    result = CiscoVendor().get_log_buffer(_FakeDevice(), "pw")

    assert result == "Sep 14 17:14:23: %SYS-5-CONFIG_I: ..."
    assert captured["all_commands"] == [
        ["show logging | exclude CFGLOG_LOGGEDCMD"],
        ["show clock"],
        ["show logging | include ^(Sep 14|Sep 13|Sep 12) "],
    ]


def test_get_log_buffer_fallback_tolerates_its_own_partial_read(monkeypatch):
    from app.services.vendors.cisco import driver as driver_module

    partial = "Sep 12 02:35:38: %C4K_L2MAN-6-INVALIDSOURCEADDRESSPACKET: (Suppr"
    fake_run, captured = _fake_clock_and_log_run(_make_run_result(rc=1, stdouts=["old stuff"]))
    captured["fallback_result"] = _make_run_result(rc=1, stdouts=[partial])
    monkeypatch.setattr(ansible_service, "run_playbook", fake_run)
    monkeypatch.setattr(driver_module, "_LOG_WINDOW_DAYS", 3)

    result = CiscoVendor().get_log_buffer(_FakeDevice(), "pw")

    assert result == partial


def test_get_log_buffer_still_raises_when_nothing_captured(monkeypatch):
    fake_run, captured = _fake_clock_and_log_run(_make_run_result(rc=1, stdouts=[]))
    monkeypatch.setattr(ansible_service, "run_playbook", fake_run)

    with pytest.raises(RuntimeError, match="cisco-01"):
        CiscoVendor().get_log_buffer(_FakeDevice(), "pw")

    assert captured["all_commands"] == [["show logging | exclude CFGLOG_LOGGEDCMD"]]


def test_get_log_buffer_raises_on_unparseable_clock(monkeypatch):
    fake_run, captured = _fake_clock_and_log_run(
        _make_run_result(rc=1, stdouts=["partial old content"]),
        clock="garbage output, no date here",
    )
    monkeypatch.setattr(ansible_service, "run_playbook", fake_run)

    with pytest.raises(RuntimeError, match="Cannot parse 'show clock'"):
        CiscoVendor().get_log_buffer(_FakeDevice(), "pw")


def test_parse_cisco_mac_tolerates_multi_word_type():
    from app.services.parsers.arp_mac_parser import parse_cisco_mac

    raw = "   7      02a0.b100.0002   dynamic ip,ipx,assigned,other Port-channel1              "
    entries = parse_cisco_mac(raw)

    assert entries == [{
        "mac": "02a0.b100.0002", "vlan": "7",
        "type": "dynamic ip,ipx,assigned,other", "interface": "Port-channel1",
    }]


def test_parse_cisco_mac_single_word_type_still_works():
    from app.services.parsers.arp_mac_parser import parse_cisco_mac

    assert parse_cisco_mac(" 156    02a0.b100.0003    DYNAMIC     Gi1/0/24") == [
        {"mac": "02a0.b100.0003", "vlan": "156", "type": "DYNAMIC", "interface": "Gi1/0/24"}
    ]
    assert parse_cisco_mac(" All    0100.0ccc.cccc STATIC      CPU") == [
        {"mac": "0100.0ccc.cccc", "vlan": "All", "type": "STATIC", "interface": "CPU"}
    ]


def test_cisco_search_mac_table_sends_include_filter(monkeypatch):
    captured = {}
    mac_output = (
        "          Mac Address Table\n"
        "-------------------------------------------\n"
        "Vlan    Mac Address       Type        Ports\n"
        "----    -----------       --------    -----\n"
        "  10    aabb.ccdd.eeff    DYNAMIC     Gi1/0/1\n"
    )

    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        captured["commands"] = extravars.get("commands")
        return _make_run_result(rc=0, stdouts=[mac_output])

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    entries = CiscoVendor().search_mac_table("aabb.ccdd.eeff", _FakeDevice(), "pw")

    assert captured["commands"] == ["show mac address-table | include aabb.ccdd.eeff"]
    assert len(entries) == 1
    assert entries[0]["mac"].lower() == "aabb.ccdd.eeff"


def test_huawei_search_mac_table_sends_include_filter(monkeypatch):
    captured = {}

    def _fake_run(playbook, extravars, inventory=None, device=None, vendor=None):
        captured["commands"] = extravars.get("commands")
        return _make_run_result(rc=0, stdouts=[""])

    monkeypatch.setattr(ansible_service, "run_playbook", _fake_run)

    class _FakeHuaweiDevice(_FakeDevice):
        vendor = "huawei_vrp"

    HuaweiVendor().search_mac_table("aabb-ccdd-eeff", _FakeHuaweiDevice(), "pw")

    assert captured["commands"] == ["display mac-address | include aabb-ccdd-eeff"]


def test_base_search_mac_table_raises_not_implemented():
    from app.services.vendors.base import VendorDriver

    with pytest.raises(NotImplementedError):
        VendorDriver.search_mac_table(MagicMock(__class__=VendorDriver), "x", _FakeDevice(), "pw")


def test_search_mac_task_marks_job_completed_with_entries(monkeypatch):
    from app.models.job import Job
    from app import tasks as tasks_module

    job = Job(operation="mac_search", device="swcs011", parameters={"pattern": "aabb"})

    class _FakeJobRepo:
        def __init__(self):
            self.saved = []

        def get(self, job_id):
            return job if job_id == job.job_id else None

        def add(self, j):
            self.saved.append(j)

    class _FakeDriver:
        def search_mac_table(self, pattern, device, password):
            assert pattern == "aabb"
            return [{"mac": "aabb.ccdd.eeff", "vlan": "10", "interface": "Gi1/0/1", "type": "DYNAMIC"}]

    fake_device = MagicMock()
    fake_device.driver = _FakeDriver()
    fake_device.password = "pw"

    class _FakeDeviceRepo:
        def get(self, name):
            return fake_device if name == "swcs011" else None

    fake_job_repo = _FakeJobRepo()
    monkeypatch.setattr(
        tasks_module, "celery_app",
        MagicMock(task=lambda **kw: (lambda fn: fn)),
    )
    import app.composition as composition_module
    monkeypatch.setattr(composition_module, "job_repository", fake_job_repo, raising=False)
    monkeypatch.setattr(composition_module, "device_repository", _FakeDeviceRepo(), raising=False)

    tasks_module.search_mac_task(fake_device.name if False else "swcs011", "aabb", job.job_id)

    assert job.status == "completed"
    assert job.result == {
        "entries": [{"mac": "aabb.ccdd.eeff", "vlan": "10", "interface": "Gi1/0/1", "type": "DYNAMIC"}],
        "pattern": "aabb",
    }


def test_search_mac_task_marks_job_failed_on_driver_error(monkeypatch):
    from app.models.job import Job
    from app import tasks as tasks_module

    job = Job(operation="mac_search", device="swcs011", parameters={"pattern": "aabb"})

    class _FakeJobRepo:
        def get(self, job_id):
            return job if job_id == job.job_id else None

        def add(self, j):
            pass

    class _FakeDriver:
        def search_mac_table(self, pattern, device, password):
            raise RuntimeError("Connection to 10.237.61.75 closed by remote host.")

    fake_device = MagicMock()
    fake_device.driver = _FakeDriver()
    fake_device.password = "pw"

    class _FakeDeviceRepo:
        def get(self, name):
            return fake_device if name == "swcs011" else None

    import app.composition as composition_module
    monkeypatch.setattr(composition_module, "job_repository", _FakeJobRepo(), raising=False)
    monkeypatch.setattr(composition_module, "device_repository", _FakeDeviceRepo(), raising=False)

    tasks_module.search_mac_task("swcs011", "aabb", job.job_id)

    assert job.status == "failed"
    assert "closed by remote host" in job.error


_MAC_SEARCH_PAYLOAD = {
    "name": "mac-search-dev",
    "host": "192.168.1.11",
    "vendor": "cisco_ios",
    "username": "admin",
    "password": "admin",
    "site_id": 1,
}


@pytest.fixture(autouse=True)
def _cleanup_mac_search_device():
    from app.db.models import DeviceModel
    from app.db.session import get_session

    def _clear():
        with get_session() as session:
            session.query(DeviceModel).filter_by(name=_MAC_SEARCH_PAYLOAD["name"]).delete(
                synchronize_session=False
            )

    _clear()
    yield
    _clear()


def test_search_endpoint_validates_include_pattern(admin_client):
    admin_client.post("/api/v1/devices/", json=_MAC_SEARCH_PAYLOAD)
    r = admin_client.post(
        f"/api/v1/devices/{_MAC_SEARCH_PAYLOAD['name']}/global-config/mac/search",
        params={"include": "not valid; has spaces and semicolons"},
    )
    assert r.status_code == 422


def test_search_endpoint_creates_job_and_runs_task(admin_client):
    admin_client.post("/api/v1/devices/", json=_MAC_SEARCH_PAYLOAD)

    r = admin_client.post(
        f"/api/v1/devices/{_MAC_SEARCH_PAYLOAD['name']}/global-config/mac/search",
        params={"include": "aabb.ccdd.eeff"},
    )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert "job_id" in body

    job_resp = admin_client.get(f"/api/v1/jobs/{body['job_id']}")
    assert job_resp.status_code == 200
    job_data = job_resp.json()["data"]
    assert job_data["status"] in ("completed", "failed")
    assert job_data["operation"] == "mac_search"


def test_cisco_reads_disable_both_pager_and_line_wrap(monkeypatch):
    from app.services import ssh_direct_service

    captured = {}

    def _fake_interactive(device, lines, known_extra_opts=None):
        captured["lines"] = lines
        return 0, "some output\nf2r11s1#quit", "", []

    monkeypatch.setattr(ssh_direct_service, "_run_ssh_interactive", _fake_interactive)

    class _Dev:
        name = "swcs011"
        vendor = "cisco_ios"

    ssh_direct_service._run_reads(_Dev(), ["show logging | include ^(Sep 14) "], op_label="test")

    assert captured["lines"] == [
        "terminal length 0", "terminal width 0", "show logging | include ^(Sep 14) ",
    ]


def test_extraer_salida_comando_tolerates_trailing_space_in_command():
    from app.services import ssh_direct_service

    command = "show logging | include ^(Sep 14) "
    raw = (
        "swcs011.lab#terminal length 0\n"
        "swcs011.lab#terminal width 0\n"
        f"swcs011.lab#{command}\n"
        "Sep 14 17:14:23: %SYS-5-CONFIG_I: Configured from console\n"
        "swcs011.lab#quit"
    )

    result = ssh_direct_service._extraer_salida_comando(raw, command)

    assert result == "Sep 14 17:14:23: %SYS-5-CONFIG_I: Configured from console"
    assert "terminal width" not in result
    assert "include" not in result


def test_exito_rejects_clean_rc_when_session_never_reached_our_quit():
    from app.services import ssh_direct_service

    truncated_no_quit_echo = (
        "swcs011.lab#show logging\n"
        "Sep 14 17:14:12: %PARSER-5-CFGLOG_LOGGEDCMD: Topology Cha"
    )

    assert ssh_direct_service._exito(truncated_no_quit_echo, truncated_no_quit_echo, vendor="cisco_ios") is False


def test_exito_accepts_clean_rc_when_session_reached_our_quit():
    from app.services import ssh_direct_service

    complete = (
        "swcs011.lab#show logging\n"
        "Sep 14 17:14:23: %SYS-5-CONFIG_I: Configured from console\n"
        "swcs011.lab#exit"
    )

    assert ssh_direct_service._exito(complete, complete, vendor="cisco_ios") is True


def test_run_reads_fuses_all_commands_into_one_ssh_session(monkeypatch):
    from app.services import ssh_direct_service

    state = {"calls": 0}
    transcript = (
        "<swhw01>screen-length 0 temporary\n"
        "<swhw01>display version\n"
        "VRP version 5.130\n"
        "<swhw01>display vlan\n"
        "VLAN ID  Name\n"
        "1        default\n"
        "<swhw01>display interface brief\n"
        "Eth0/0/1  up\n"
        "<swhw01>quit"
    )

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        state["calls"] += 1
        tiene_opcion = any("HostKeyAlgorithms=+ssh-rsa" in part for part in cmd)
        class _Proc:
            pass
        proc = _Proc()
        if tiene_opcion:
            proc.returncode = 0
            proc.stdout = transcript
            proc.stderr = ""
        else:
            proc.returncode = 255
            proc.stdout = ""
            proc.stderr = (
                "Unable to negotiate with 10.237.61.210 port 22: no matching "
                "host key type found. Their offer: ssh-rsa"
            )
        return proc

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "swhw01"
        host = "10.237.61.210"
        username = "netconf"
        vendor = "huawei_vrp"

    result = ssh_direct_service._run_reads(
        _Dev(), ["display version", "display vlan", "display interface brief"],
        op_label="test",
    )

    assert state["calls"] == 2
    assert result["rc"] == 0
    assert result["stdouts"] == [
        "VRP version 5.130",
        "VLAN ID  Name\n1        default",
        "Eth0/0/1  up",
    ]


def test_run_reads_flags_session_incomplete_when_truncated_mid_batch(monkeypatch):
    from app.services import ssh_direct_service

    transcript = (
        "swcs010#terminal length 0\n"
        "swcs010#terminal width 0\n"
        "swcs010#show interfaces status\n"
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi1/0/1                      connected    157        a-full  a-100 10/100/1000BaseTX\n"
        "swcs010#"
    )

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        class _Proc:
            returncode = 0
            stdout = transcript
            stderr = ""
        return _Proc()

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "swcs010"
        host = "192.0.2.1"
        username = "admin"
        vendor = "cisco_ios"

    result = ssh_direct_service._run_reads(
        _Dev(),
        [
            "show interfaces status", "show interfaces description",
            "show interfaces switchport", "show storm-control broadcast",
            "show running-config | section ^interface",
        ],
        op_label="test",
    )

    assert result["session_complete"] is False
    assert result["rc"] == 1
    assert "Gi1/0/1" in result["stdouts"][0]
    assert result["stdouts"][1:] == ["", "", "", ""]


def test_extraer_salidas_comandos_handles_session_cut_mid_batch():
    from app.services import ssh_direct_service

    raw = (
        "<dev>display version\n"
        "VRP version 5.130\n"
        "Connection reset by peer"
    )
    result = ssh_direct_service._extraer_salidas_comandos(
        raw, ["display version", "display vlan", "display interface brief"],
    )

    assert result[0] == "VRP version 5.130\nConnection reset by peer"
    assert result[1] == ""
    assert result[2] == ""


def test_run_ssh_paced_delays_quit_after_draining_period(monkeypatch):
    from app.services import ssh_direct_service

    writes: list[str] = []

    class _FakeClock:
        def __init__(self):
            self.t = 0.0
        def monotonic(self):
            return self.t
        def sleep(self, s):
            self.t += s

    clock = _FakeClock()

    class _FakeStdin:
        def write(self, data):
            writes.append(data)
        def flush(self):
            pass
        def close(self):
            pass

    class _FakePopen:
        def __init__(self, cmd, stdin=None, stdout=None, stderr=None, text=None, env=None, bufsize=None):
            self.stdin = _FakeStdin()
            self.returncode = 0
        def poll(self):
            return None
        def communicate(self, timeout=None):
            return "ok\ndev#quit", ""

    monkeypatch.setattr(ssh_direct_service.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(ssh_direct_service.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ssh_direct_service.time, "sleep", clock.sleep)
    monkeypatch.setattr(ssh_direct_service, "_SSH_DRAIN_DELAY_S", 2.0)

    proc = ssh_direct_service._run_ssh_paced(
        ["ssh", "dev"], ["terminal length 0", "show interfaces switchport"], {},
    )

    assert writes == ["terminal length 0\nshow interfaces switchport\n", "quit\n"]
    assert clock.t >= 2.0
    assert proc.returncode == 0
    assert proc.stdout == "ok\ndev#quit"


def test_run_ssh_paced_survives_broken_pipe_on_late_write(monkeypatch):
    from app.services import ssh_direct_service

    class _FakeStdin:
        def write(self, data):
            if data == "quit\n":
                raise BrokenPipeError("device closed the channel")
        def flush(self):
            pass
        def close(self):
            pass

    class _FakePopen:
        def __init__(self, cmd, stdin=None, stdout=None, stderr=None, text=None, env=None, bufsize=None):
            self.stdin = _FakeStdin()
            self.returncode = 1
        def poll(self):
            return None
        def communicate(self, timeout=None):
            return "partial output before the cut", "Connection closed by remote host"

    monkeypatch.setattr(ssh_direct_service.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(ssh_direct_service.time, "sleep", lambda s: None)
    monkeypatch.setattr(ssh_direct_service, "_SSH_DRAIN_DELAY_S", 0)

    proc = ssh_direct_service._run_ssh_paced(["ssh", "dev"], ["show interfaces switchport"], {})

    assert proc.returncode == 1
    assert proc.stdout == "partial output before the cut"


def test_run_ssh_interactive_tries_default_algorithms_first(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            returncode = 0
            stdout = "ok\nf2r11s1#quit"
            stderr = ""
        return _Proc()

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "somedevice"
        host = "192.0.2.1"
        username = "admin"

    ssh_direct_service._run_ssh_interactive(_Dev(), ["show version"])

    assert len(captured_cmds) == 1
    assert not any("KexAlgorithms" in part for part in captured_cmds[0])


def test_run_ssh_interactive_retries_with_devices_own_kex_offer(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            pass
        proc = _Proc()
        if len(captured_cmds) == 1:
            proc.returncode = 255
            proc.stdout = ""
            proc.stderr = (
                "Unable to negotiate with 192.0.2.1 port 22: no matching key "
                "exchange method found. Their offer: totally-made-up-kex-2000"
            )
        else:
            proc.returncode = 0
            proc.stdout = "ok\nsomedevice#quit"
            proc.stderr = ""
        return proc

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "somedevice"
        host = "192.0.2.1"
        username = "admin"

    rc, stdout, stderr, _ = ssh_direct_service._run_ssh_interactive(_Dev(), ["show version"])

    assert len(captured_cmds) == 2
    assert not any("KexAlgorithms" in part for part in captured_cmds[0])
    assert "KexAlgorithms=+totally-made-up-kex-2000" in captured_cmds[1]
    assert rc == 0
    assert stdout == "ok\nsomedevice#quit"


def test_run_ssh_interactive_retries_host_key_type_sets_both_options(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            pass
        proc = _Proc()
        if len(captured_cmds) == 1:
            proc.returncode = 255
            proc.stdout = ""
            proc.stderr = (
                "Unable to negotiate with 10.237.61.210 port 22: no matching "
                "host key type found. Their offer: ssh-rsa"
            )
        else:
            proc.returncode = 0
            proc.stdout = "ok\nf3r9s2#quit"
            proc.stderr = ""
        return proc

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "swhw01"
        host = "10.237.61.210"
        username = "netconf"

    ssh_direct_service._run_ssh_interactive(_Dev(), ["display logbuffer"])

    assert "HostKeyAlgorithms=+ssh-rsa" in captured_cmds[1]
    assert "PubkeyAcceptedKeyTypes=+ssh-rsa" in captured_cmds[1]


def test_run_ssh_interactive_stops_retrying_when_same_category_repeats(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            returncode = 255
            stdout = ""
            stderr = (
                "Unable to negotiate with 192.0.2.1 port 22: no matching key "
                "exchange method found. Their offer: some-kex-nobody-supports"
            )
        return _Proc()

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "somedevice"
        host = "192.0.2.1"
        username = "admin"

    rc, stdout, stderr, _ = ssh_direct_service._run_ssh_interactive(_Dev(), ["show version"])

    assert len(captured_cmds) == 2
    assert rc == 255


def test_run_ssh_interactive_does_not_retry_on_unrelated_failure(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            returncode = 255
            stdout = ""
            stderr = "Permission denied (publickey)."
        return _Proc()

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "somedevice"
        host = "192.0.2.1"
        username = "admin"

    ssh_direct_service._run_ssh_interactive(_Dev(), ["show version"])

    assert len(captured_cmds) == 1


class _NullAgentCtx:
    def __enter__(self):
        return {}

    def __exit__(self, *a):
        return False


def test_run_ssh_interactive_adapts_cipher_too(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            pass
        proc = _Proc()
        if len(captured_cmds) == 1:
            proc.returncode = 255
            proc.stdout = ""
            proc.stderr = (
                "Unable to negotiate with 10.237.61.53 port 22: no matching "
                "cipher found. Their offer: aes128-cbc,3des-cbc,aes192-cbc,aes256-cbc"
            )
        else:
            proc.returncode = 0
            proc.stdout = "ok\nf2r6s3#quit"
            proc.stderr = ""
        return proc

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "swcs02"
        host = "10.237.61.53"
        username = "ansiauthtest"

    rc, stdout, stderr, _ = ssh_direct_service._run_ssh_interactive(_Dev(), ["show version"])

    assert len(captured_cmds) == 2
    assert "Ciphers=+aes128-cbc,3des-cbc,aes192-cbc,aes256-cbc" in captured_cmds[1]
    assert rc == 0


def test_run_ssh_interactive_adapts_all_three_categories_in_sequence(monkeypatch):
    from app.services import ssh_direct_service

    captured_cmds = []
    failures = [
        "Unable to negotiate with 10.237.61.53 port 22: no matching key "
        "exchange method found. Their offer: diffie-hellman-group14-sha1",
        "Unable to negotiate with 10.237.61.53 port 22: no matching host "
        "key type found. Their offer: ssh-rsa",
        "Unable to negotiate with 10.237.61.53 port 22: no matching "
        "cipher found. Their offer: aes128-cbc,3des-cbc,aes192-cbc,aes256-cbc",
    ]

    def _fake_run(cmd, input, capture_output, text, timeout, env):
        captured_cmds.append(cmd)
        class _Proc:
            pass
        proc = _Proc()
        attempt = len(captured_cmds)
        if attempt <= len(failures):
            proc.returncode = 255
            proc.stdout = ""
            proc.stderr = failures[attempt - 1]
        else:
            proc.returncode = 0
            proc.stdout = "ok\nf2r6s3#quit"
            proc.stderr = ""
        return proc

    _patch_ssh_paced(monkeypatch, _fake_run)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Dev:
        name = "swcs02"
        host = "10.237.61.53"
        username = "ansiauthtest"

    rc, stdout, stderr, _ = ssh_direct_service._run_ssh_interactive(_Dev(), ["show version"])

    assert len(captured_cmds) == 4
    final_cmd = captured_cmds[3]
    assert "KexAlgorithms=+diffie-hellman-group14-sha1" in final_cmd
    assert "HostKeyAlgorithms=+ssh-rsa" in final_cmd
    assert "PubkeyAcceptedKeyTypes=+ssh-rsa" in final_cmd
    assert "Ciphers=+aes128-cbc,3des-cbc,aes192-cbc,aes256-cbc" in final_cmd
    assert rc == 0
    assert stdout == "ok\nf2r6s3#quit"


def test_terminador_por_vendor():
    from app.services import ssh_direct_service as ssh

    assert ssh._terminador("cisco_ios") == "exit"
    assert ssh._terminador("huawei_vrp") == "quit"
    assert ssh._terminador(None) == "quit"
    assert ssh._terminador("otro") == "quit"


def test_run_ssh_interactive_manda_exit_a_cisco_y_quit_a_huawei(monkeypatch):
    from app.services import ssh_direct_service

    enviados: list[tuple[str, list[str]]] = []

    def _fake_paced(cmd, lines, env, terminador="quit"):
        enviados.append((terminador, list(lines)))

        class _Proc:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return _Proc()

    monkeypatch.setattr(ssh_direct_service, "_run_ssh_paced", _fake_paced)
    monkeypatch.setattr(ssh_direct_service, "_agent_for", lambda device: _NullAgentCtx())

    class _Cisco:
        name, host, username, vendor = "c", "192.0.2.1", "admin", "cisco_ios"

    class _Huawei:
        name, host, username, vendor = "h", "192.0.2.2", "admin", "huawei_vrp"

    ssh_direct_service._run_ssh_interactive(_Cisco(), ["show version"])
    ssh_direct_service._run_ssh_interactive(_Huawei(), ["display version"])

    assert [t for t, _ in enviados] == ["exit", "quit"]


def test_run_ssh_paced_escribe_el_terminador_recibido(monkeypatch):
    from app.services import ssh_direct_service

    writes: list[str] = []

    class _FakeStdin:
        def write(self, data):
            writes.append(data)
        def flush(self):
            pass
        def close(self):
            pass

    class _FakePopen:
        def __init__(self, cmd, stdin=None, stdout=None, stderr=None, text=None, env=None, bufsize=None):
            self.stdin = _FakeStdin()
            self.returncode = 0
        def poll(self):
            return 0
        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setattr(ssh_direct_service.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(ssh_direct_service, "_SSH_DRAIN_DELAY_S", 0)

    ssh_direct_service._run_ssh_paced(["ssh", "dev"], ["show version"], {}, "exit")

    assert writes == ["show version\n", "exit\n"]


def test_sesion_completa_reconoce_solo_el_terminador_de_su_vendor():
    from app.services import ssh_direct_service as ssh

    cisco = "swcs03.lab#show version\nIOS 15\nf2r3s2.lab#exit"
    huawei = "<swhw01>display version\nVRP 5.130\n<swhw01>quit"

    assert ssh._sesion_completa(cisco, "cisco_ios")
    assert ssh._sesion_completa(huawei, "huawei_vrp")
    assert not ssh._sesion_completa(cisco.replace("exit", "quit"), "cisco_ios")
    assert not ssh._sesion_completa(huawei.replace("quit", "exit"), "huawei_vrp")


def test_extraer_salidas_corta_en_el_terminador_de_su_vendor():
    from app.services import ssh_direct_service as ssh

    raw = "dev#show version\nIOS 15\ndev#exit"
    assert ssh._extraer_salidas_comandos(raw, ["show version"], "cisco_ios") == ["IOS 15"]
    assert ssh._extraer_salida_comando(raw, "show version", "cisco_ios") == "IOS 15"

    raw_h = "<dev>display version\nVRP 5.130\n<dev>quit"
    assert ssh._extraer_salidas_comandos(raw_h, ["display version"], "huawei_vrp") == ["VRP 5.130"]


def test_running_config_cisco_con_quit_legitimo_no_corta_la_salida():
    from app.services import ssh_direct_service as ssh

    raw = (
        "dev#show running-config\n"
        "crypto pki certificate chain TP-self-signed\n"
        "  certificate self-signed 01\n"
        "  quit\n"
        "hostname dev\n"
        "dev#exit"
    )
    salida = ssh._extraer_salidas_comandos(raw, ["show running-config"], "cisco_ios")[0]
    assert salida.endswith("hostname dev")
    assert "quit" in salida
