import logging
import os
import tempfile

import ansible_runner as _runner

from app.core.config import ANSIBLE_BASE_PATH, INVENTORY_PATH

logger = logging.getLogger(__name__)

_ANSIBLE_TIMEOUT = os.environ.get("ANSIBLE_TIMEOUT", "60")
_ANSIBLE_PERSISTENT_COMMAND_TIMEOUT = os.environ.get("ANSIBLE_PERSISTENT_COMMAND_TIMEOUT", "60")
_ANSIBLE_PERSISTENT_CONNECT_TIMEOUT = os.environ.get("ANSIBLE_PERSISTENT_CONNECT_TIMEOUT", "60")


def _mask_inventory(inv_str: str) -> str:
    marker = "ansible_password="
    idx = inv_str.find(marker)
    if idx == -1:
        return inv_str
    value_start = idx + len(marker)
    value_end = inv_str.find(" ", value_start)
    if value_end == -1:
        value_end = len(inv_str)
    return inv_str[:value_start] + "***REDACTED***" + inv_str[value_end:]


def run_playbook(
    playbook: str,
    extravars: dict,
    inventory: str | None = None,
    device: str | None = None,
    vendor: str | None = None,
) -> dict:
    if inventory is None:
        logger.warning("No dynamic inventory provided for playbook=%s, falling back to %s", playbook, INVENTORY_PATH)
    inv = inventory or INVENTORY_PATH
    device_label = device or extravars.get("device", "unknown")

    resolved_playbook = os.path.join(ANSIBLE_BASE_PATH, "project", playbook)
    logger.info(
        "[DIAG] Running playbook=%s device=%s private_data_dir=%s extravars=%s",
        playbook,
        device_label,
        ANSIBLE_BASE_PATH,
        extravars,
    )
    logger.info(
        "[DIAG] Resolved playbook path: %s",
        resolved_playbook,
    )
    logger.info(
        "[DIAG] Execution cwd=%s",
        os.getcwd(),
    )
    logger.info(
        "[DIAG] Path existence: private_data_dir=%s  resolved_playbook=%s",
        os.path.exists(ANSIBLE_BASE_PATH),
        os.path.exists(resolved_playbook),
    )
    logger.info(
        "[DIAG] Ansible timeout config: ANSIBLE_TIMEOUT=%s  ANSIBLE_PERSISTENT_COMMAND_TIMEOUT=%s  ANSIBLE_PERSISTENT_CONNECT_TIMEOUT=%s",
        _ANSIBLE_TIMEOUT,
        _ANSIBLE_PERSISTENT_COMMAND_TIMEOUT,
        _ANSIBLE_PERSISTENT_CONNECT_TIMEOUT,
    )

    if isinstance(inv, str) and not os.path.exists(inv):
        logger.info(
            "[DIAG] Generated inventory for device=%s (inline, will be written to temp file):\n%s",
            device_label,
            _mask_inventory(inv),
        )
    else:
        logger.info("[DIAG] Using existing inventory path: %s", inv)

    _temp_inv = None
    if isinstance(inv, str) and not os.path.exists(inv):
        _temp_inv = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False)
        _temp_inv.write("[all]\n")
        _temp_inv.write(inv + "\n")
        _temp_inv.close()
        inv = _temp_inv.name
        logger.info("[DIAG] Temp inventory file written to: %s  exists=%s", inv, os.path.exists(inv))

    logger.info(
        "[DIAG] ansible_runner.run args: playbook=%s  private_data_dir=%s  inventory=%s  extravars=%s  quiet=True",
        playbook,
        ANSIBLE_BASE_PATH,
        inv,
        extravars,
    )

    from app.composition import redis_coordinator

    try:
        with redis_coordinator.adquirir_slot():
            r = _runner.run(
                private_data_dir=ANSIBLE_BASE_PATH,
                playbook=playbook,
                inventory=inv,
                extravars=extravars,
                quiet=True,
                suppress_env_files=True,
                envvars={
                    "ANSIBLE_TIMEOUT": _ANSIBLE_TIMEOUT,
                    "ANSIBLE_PERSISTENT_COMMAND_TIMEOUT": _ANSIBLE_PERSISTENT_COMMAND_TIMEOUT,
                    "ANSIBLE_PERSISTENT_CONNECT_TIMEOUT": _ANSIBLE_PERSISTENT_CONNECT_TIMEOUT,
                    "ANSIBLE_HOST_KEY_CHECKING": "True",
                    "ANSIBLE_HOST_KEY_AUTO_ADD": "True",
                    "ANSIBLE_PARAMIKO_HOST_KEY_AUTO_ADD": "True",
                },
            )
    finally:
        if _temp_inv is not None:
            os.unlink(_temp_inv.name)

    rc = r.rc
    raw_stderr = _read(r.stderr)
    raw_stdout = _read(r.stdout)

    logger.info(
        "[DIAG] Playbook completed: playbook=%s device=%s rc=%s status=%s",
        playbook,
        device_label,
        rc,
        getattr(r, "status", "unknown"),
    )
    logger.info("[DIAG] Playbook stdout:\n%s", raw_stdout)
    logger.info("[DIAG] Playbook stderr:\n%s", raw_stderr)

    stderr = raw_stderr
    failure_reason = _extract_failure_reason(r) if rc != 0 else ""
    ios_cmd_output = _extract_ios_command_output(r)
    if rc != 0 and failure_reason:
        stdout = failure_reason
    elif ios_cmd_output:
        stdout = ios_cmd_output
    else:
        stdout = raw_stdout
    stdouts = _extract_all_command_outputs(r)
    combined_output = (stdout + stderr).lower()
    if "no hosts matched" in combined_output and rc == 0:
        logger.error("Playbook %s: no hosts matched on device=%s — treating as failure", playbook, device_label)
        rc = 1
        stderr = stderr or "No hosts matched in inventory"
        stdouts = []
    if rc == 0 and stdout == "None":
        logger.warning(
            "Playbook %s: rc=0 but stdout is the literal string 'None' on device=%s "
            "-- treating as an unreliable read, forcing a retry",
            playbook, device_label,
        )
        rc = 1
        stderr = "ansible reported success with no readable output (stdout=='None') -- possible read desync, retrying"
        stdout = ""
        stdouts = []
    if rc == 0 and stdout:
        from app.services.vendors.base import _tiene_error

        if _tiene_error(stdout, vendor):
            logger.warning(
                "Playbook %s: rc=0 pero el device rechazó el comando (device=%s, vendor=%s) -- "
                "forzando rc=1: %s",
                playbook, device_label, vendor, stdout[:300],
            )
            rc = 1
            stderr = stderr or "device rejected the command (detected in echoed stdout)"
    result = {"rc": rc, "stdout": stdout, "stderr": stderr, "stdouts": stdouts}
    logger.debug("Ansible raw result: %s", result)
    if rc != 0:
        error_output = (stderr + " " + stdout).strip()
        logger.error("Playbook %s FAILED on device=%s rc=%s error=%s", playbook, device_label, rc, error_output[:1000])
    else:
        logger.info("Playbook %s SUCCESS on device=%s rc=%s", playbook, device_label, rc)
    return result


def build_inventory(
    device_id: str,
    ip: str,
    username: str,
    password: str,
    network_os: str = "ios",
    connection: str = "network_cli",
    port: int | None = None,
) -> str:
    logger.info(
        "[DIAG] Inventory host vars for %s: host=%s user=%s network_os=%s connection=%s port=%s",
        device_id,
        ip,
        username,
        network_os,
        connection,
        port,
    )
    inv = (
        f"{device_id} "
        f"ansible_host={ip} "
        f"ansible_user={username} "
        f"ansible_password={password} "
        f"ansible_network_os={network_os} "
        f"ansible_connection={connection}"
    )
    if port is not None:
        inv += f" ansible_port={port}"
    return inv


def _extract_ios_command_output(r) -> str:
    try:
        for event in r.events:
            if event.get("event") == "runner_on_ok":
                res = event.get("event_data", {}).get("res", {})
                stdout_val = res.get("stdout")
                if isinstance(stdout_val, list) and stdout_val:
                    logger.debug("Extracted list-format command output from events (%d chars)", len(stdout_val[0]))
                    return stdout_val[0]
                if isinstance(stdout_val, str) and stdout_val:
                    logger.debug("Extracted string-format command output from events (%d chars)", len(stdout_val))
                    return stdout_val
    except Exception as exc:
        logger.debug("Could not extract command output from events: %s", exc)
    return ""


def _extract_all_command_outputs(r) -> list[str]:
    outputs: list[str] = []
    try:
        for event in r.events:
            if event.get("event") not in ("runner_on_ok", "runner_on_failed"):
                continue
            res = event.get("event_data", {}).get("res", {})
            results = res.get("results")
            if isinstance(results, list):
                for item in results:
                    if not isinstance(item, dict):
                        outputs.append("")
                        continue
                    item_stdout = item.get("stdout")
                    if isinstance(item_stdout, str):
                        outputs.append(item_stdout)
                    elif isinstance(item_stdout, list) and item_stdout:
                        first = item_stdout[0]
                        outputs.append(first if isinstance(first, str) else "")
                    else:
                        outputs.append("")
                continue
            stdout_val = res.get("stdout")
            if isinstance(stdout_val, list):
                for entry in stdout_val:
                    if isinstance(entry, str):
                        outputs.append(entry)
            elif isinstance(stdout_val, str):
                outputs.append(stdout_val)
    except Exception as exc:
        logger.debug("Could not extract command outputs from events: %s", exc)
    logger.debug("Extracted %d command output(s) from events", len(outputs))
    return outputs


def _extract_failure_reason(r) -> str:
    try:
        for event in r.events:
            if event.get("event") in ("runner_on_failed", "runner_on_unreachable"):
                data = event.get("event_data", {})
                res = data.get("res", {})
                results = res.get("results")
                if isinstance(results, list):
                    for item in results:
                        if isinstance(item, dict) and item.get("failed"):
                            item_msg = (
                                item.get("msg") or item.get("stderr") or item.get("stdout")
                            )
                            if item_msg:
                                item_label = item.get("item", "")
                                combined = f"[{item_label}] {item_msg}" if item_label else str(item_msg)
                                logger.debug("Extracted per-item failure reason from loop results: %s", combined[:200])
                                return combined
                msg = res.get("msg") or res.get("stdout") or data.get("task", "")
                if msg:
                    logger.debug("Extracted failure reason from events: %s", str(msg)[:200])
                    return str(msg)
    except Exception as exc:
        logger.debug("Could not extract failure reason from events: %s", exc)
    return ""


def _read(stream) -> str:
    if not stream:
        return ""
    try:
        return stream.read() if hasattr(stream, "read") else str(stream)
    except Exception:
        return ""
