import contextlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from app.core.config import ANSIBLE_BASE_PATH
from app.services import known_hosts
from app.services.vendors.base import _tiene_error
from app.services.vendors.base import limpiar_ruido_benigno as _limpiar_ruido_benigno

logger = logging.getLogger(__name__)

_SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_DIRECT_CONNECT_TIMEOUT", "15"))
_SSH_COMMAND_TIMEOUT = int(os.environ.get("SSH_DIRECT_COMMAND_TIMEOUT", "60"))
_SSH_DRAIN_DELAY_S = float(os.environ.get("SSH_DIRECT_DRAIN_DELAY", "5.0"))

_NEGOTIATION_FAILURE_RE = re.compile(
    r"no matching (key exchange method|host key type|cipher) found\. "
    r"Their offer: ([\w@.,\-]+)"
)
_NEGOTIATION_OPTION_NAMES: "dict[str, list[str]]" = {
    "key exchange method": ["KexAlgorithms"],
    "host key type": ["HostKeyAlgorithms", "PubkeyAcceptedKeyTypes"],
    "cipher": ["Ciphers"],
}
_MAX_NEGOTIATION_RETRIES = len(_NEGOTIATION_OPTION_NAMES)

_ALGORITMOS_APRENDIDOS: "dict[str, list[str]]" = {}
_ALGORITMOS_LOCK = threading.Lock()


def _algoritmos_aprendidos(host: str) -> "list[str]":
    with _ALGORITMOS_LOCK:
        return list(_ALGORITMOS_APRENDIDOS.get(host, []))


def _recordar_algoritmos(host: str, extra_opts: "list[str]") -> None:
    with _ALGORITMOS_LOCK:
        if extra_opts:
            _ALGORITMOS_APRENDIDOS[host] = list(extra_opts)
        else:
            _ALGORITMOS_APRENDIDOS.pop(host, None)


def _sin_opciones(extra_opts: "list[str]", nombres: "list[str]") -> "list[str]":
    resultado: list[str] = []
    i = 0
    while i < len(extra_opts):
        if extra_opts[i] == "-o" and i + 1 < len(extra_opts) and extra_opts[i + 1].split("=", 1)[0] in nombres:
            i += 2
            continue
        resultado.append(extra_opts[i])
        i += 1
    return resultado

_DEVICE_KEYS_DIR = os.path.join(os.path.dirname(ANSIBLE_BASE_PATH), "device_ssh_keys")


def write_private_key_file(device_name: str, private_key: str) -> str:
    os.makedirs(_DEVICE_KEYS_DIR, mode=0o700, exist_ok=True)
    os.chmod(_DEVICE_KEYS_DIR, 0o700)
    fd, path = tempfile.mkstemp(prefix=f"{device_name}-", dir=_DEVICE_KEYS_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(private_key)
            if not private_key.endswith("\n"):
                f.write("\n")
    finally:
        os.chmod(path, 0o600)
    return path


def _start_agent(keyfile: str) -> "tuple[dict, subprocess.Popen]":
    sock_dir = tempfile.mkdtemp(prefix="agent-", dir=_DEVICE_KEYS_DIR)
    sock = os.path.join(sock_dir, "agent.sock")
    proc = subprocess.Popen(
        ["ssh-agent", "-D", "-a", sock],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    env = dict(os.environ)
    env["SSH_AUTH_SOCK"] = sock
    env["SSH_AGENT_PID"] = str(proc.pid)
    try:
        deadline = time.monotonic() + 5
        while not os.path.exists(sock):
            if proc.poll() is not None:
                raise RuntimeError(
                    f"ssh-agent could not start: {(proc.stderr.read() or '').strip() or f'rc={proc.returncode}'}"
                )
            if time.monotonic() > deadline:
                raise RuntimeError("ssh-agent did not become ready within 5s")
            time.sleep(0.02)
        add = subprocess.run(["ssh-add", keyfile], env=env, capture_output=True, text=True, timeout=5)
        if add.returncode != 0:
            raise RuntimeError(
                "Could not load the device's private key into the SSH agent: "
                f"{(add.stderr or add.stdout).strip() or f'ssh-add rc={add.returncode}'}"
            )
    except BaseException:
        _stop_agent(env, proc)
        raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(keyfile)
    return env, proc


def _stop_agent(env: dict, proc: "subprocess.Popen | None" = None) -> None:
    if proc is not None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stderr is not None:
            proc.stderr.close()
    sock = env.get("SSH_AUTH_SOCK")
    if sock:
        shutil.rmtree(os.path.dirname(sock), ignore_errors=True)


@contextlib.contextmanager
def _agent_for(device):
    keyfile = write_private_key_file(device.name, device.private_key)
    agent_env, agent_proc = _start_agent(keyfile)
    try:
        yield agent_env
    finally:
        _stop_agent(agent_env, agent_proc)


_PAGER_DISABLE = {
    "huawei_vrp": ["screen-length 0 temporary"],
    "cisco_ios": ["terminal length 0", "terminal width 0"],
}

_TERMINADOR_SESION = {
    "huawei_vrp": "quit",
    "cisco_ios": "exit",
}


def _terminador(vendor: "str | None") -> str:
    return _TERMINADOR_SESION.get(vendor, "quit")


def _run_ssh_paced(
    cmd: list[str], lines: list[str], env: dict, terminador: str = "quit",
) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, bufsize=1,
    )
    deadline = time.monotonic() + _SSH_COMMAND_TIMEOUT
    try:
        proc.stdin.write("\n".join(lines) + "\n")
        proc.stdin.flush()
        drain_until = time.monotonic() + _SSH_DRAIN_DELAY_S
        while time.monotonic() < drain_until:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        proc.stdin.write(f"{terminador}\n")
        proc.stdin.flush()
        proc.stdin.close()
        proc.stdin = None
        remaining = max(0.0, deadline - time.monotonic())
        stdout, stderr = proc.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    except BrokenPipeError:
        proc.stdin = None
        stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _run_ssh_interactive(
    device, lines: list[str], known_extra_opts: "list[str] | None" = None,
) -> tuple[int, str, str, list[str]]:
    base_cmd = [
        "ssh", "-tt",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known_hosts.KNOWN_HOSTS_DIRECTO}",
        "-o", "LogLevel=INFO",
        "-o", f"ConnectTimeout={_SSH_CONNECT_TIMEOUT}",
        "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    ]
    from app.composition import redis_coordinator

    with redis_coordinator.adquirir_slot(), _agent_for(device) as agent_env:
        if known_extra_opts is not None:
            extra_opts: list[str] = list(known_extra_opts)
        else:
            extra_opts = _algoritmos_aprendidos(device.host)
        categorias_probadas: set[str] = set()
        for _ in range(_MAX_NEGOTIATION_RETRIES + 1):
            cmd = [*base_cmd, *extra_opts, f"{device.username}@{device.host}"]
            try:
                proc = _run_ssh_paced(cmd, lines, agent_env, _terminador(getattr(device, 'vendor', None)))
            except subprocess.TimeoutExpired:
                return 1, "", f"ssh command timed out after {_SSH_COMMAND_TIMEOUT}s", extra_opts
            except Exception as exc:
                logger.exception("ssh_direct_service: interactive ssh invocation failed device=%s", device.name)
                return 1, "", str(exc), extra_opts
            m = _NEGOTIATION_FAILURE_RE.search(proc.stderr)
            if m is None:
                _recordar_algoritmos(device.host, extra_opts)
                return proc.returncode, proc.stdout, proc.stderr, extra_opts
            categoria, oferta = m.groups()
            if categoria in categorias_probadas:
                _recordar_algoritmos(device.host, [])
                return proc.returncode, proc.stdout, proc.stderr, extra_opts
            categorias_probadas.add(categoria)
            nombres = _NEGOTIATION_OPTION_NAMES.get(categoria, [])
            extra_opts = _sin_opciones(extra_opts, nombres)
            for opt_name in nombres:
                extra_opts += ["-o", f"{opt_name}=+{oferta}"]
            logger.info(
                "ssh_direct_service: negotiation failed on device=%s (%s, their offer: %s) "
                "-- retrying with that exact offer added to %s",
                device.name, categoria, oferta, _NEGOTIATION_OPTION_NAMES.get(categoria, []),
            )
        _recordar_algoritmos(device.host, [])
        return proc.returncode, proc.stdout, proc.stderr, extra_opts


def _sesion_completa(raw: str, vendor: "str | None" = None) -> bool:
    terminador = _terminador(vendor)
    lines = [l for l in raw.splitlines() if l.strip()]
    return any(line.rstrip().endswith(terminador) for line in lines[-5:])


def _exito(stdout: str, raw: str, vendor: "str | None" = None) -> bool:
    if _tiene_error(stdout, vendor):
        return False
    return _sesion_completa(raw, vendor)


def _run_write(device, block: str, *, op_label: str) -> dict:
    logger.info("ssh_direct_service: %s on device=%s", op_label, device.name)
    _, stdout, stderr, _ = _run_ssh_interactive(device, block.split("\n"))
    rc = 0 if _exito(stdout, stdout, vendor=device.vendor) else 1
    if rc == 0:
        logger.info("ssh_direct_service: %s OK on device=%s", op_label, device.name)
    else:
        logger.error(
            "ssh_direct_service: %s FAILED on device=%s — %s",
            op_label, device.name, stderr or stdout,
        )
    return {"rc": rc, "stdout": stdout, "stderr": stderr, "stdouts": [stdout] if stdout else []}


def _extraer_salida_comando(raw: str, command: str, vendor: "str | None" = None) -> str:
    command = command.rstrip()
    lines = raw.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip().endswith(command):
            start = i + 1
            break
    if start is None:
        return raw.strip("\n")
    terminador = _terminador(vendor)
    end = len(lines)
    for i in range(len(lines) - 1, start - 1, -1):
        if lines[i].rstrip().endswith(terminador):
            end = i
            break
    return "\n".join(lines[start:end]).strip("\n")


def _extraer_salidas_comandos(raw: str, commands: list[str], vendor: "str | None" = None) -> list[str]:
    lines = raw.splitlines()
    terminador = _terminador(vendor)
    quit_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].rstrip().endswith(terminador):
            quit_idx = i
            break

    echo_idxs: "list[int | None]" = []
    search_from = 0
    for command in commands:
        cmd = command.rstrip()
        found = None
        for i in range(search_from, len(lines)):
            if lines[i].rstrip().endswith(cmd):
                found = i
                break
        echo_idxs.append(found)
        if found is not None:
            search_from = found + 1

    outputs: list[str] = []
    for pos, idx in enumerate(echo_idxs):
        if idx is None:
            outputs.append("")
            continue
        end = quit_idx
        for later_idx in echo_idxs[pos + 1:]:
            if later_idx is not None:
                end = later_idx
                break
        outputs.append("\n".join(lines[idx + 1:end]).strip("\n"))
    return outputs


def _run_reads(device, commands: list[str], *, op_label: str) -> dict:
    logger.info("ssh_direct_service: %s (%d command(s)) on device=%s", op_label, len(commands), device.name)
    pager_disable = _PAGER_DISABLE.get(device.vendor, [])
    lines = [*pager_disable, *commands]
    _, raw_out, err, _extra_opts = _run_ssh_interactive(device, lines)
    stdouts = _extraer_salidas_comandos(raw_out, commands, device.vendor)
    stderrs = [err] if err else []

    session_ok = _sesion_completa(raw_out, device.vendor)
    rc = 0
    for out in stdouts:
        if not session_ok or _tiene_error(out, device.vendor):
            rc = 1
            break
    if rc != 0:
        logger.error("ssh_direct_service: %s FAILED on device=%s", op_label, device.name)
    return {
        "rc": rc,
        "stdout": stdouts[0] if stdouts else "",
        "stderr": "\n".join(stderrs),
        "stdouts": stdouts,
        "session_complete": session_ok,
    }


def _armar_bloque_cisco(lines: list[str], parents: "str | None") -> str:
    block = ["configure terminal"]
    if parents:
        block.append(parents)
    block.extend(lines)
    block.append("end")
    return "\n".join(block)


def run_direct(extravars: dict, device) -> dict:
    if "command_block" in extravars:
        return _run_write(device, extravars["command_block"], op_label="command_block")

    if "command_blocks" in extravars:
        combined = "\n".join(extravars["command_blocks"])
        return _run_write(device, combined, op_label="command_blocks (lote)")

    if "lines" in extravars:
        block = _armar_bloque_cisco(extravars["lines"], extravars.get("parents"))
        return _run_write(device, block, op_label="lines")

    if "config_steps" in extravars:
        blocks = [
            _armar_bloque_cisco(step["lines"], step.get("parents"))
            for step in extravars["config_steps"]
        ]
        return _run_write(device, "\n".join(blocks), op_label="config_steps (lote)")

    if "commands" in extravars:
        return _run_reads(device, extravars["commands"], op_label="commands")

    raise ValueError(f"ssh_direct_service.run_direct(): unsupported extravars shape {sorted(extravars)}")
