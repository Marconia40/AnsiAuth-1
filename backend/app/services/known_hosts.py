import logging
import os
import subprocess

logger = logging.getLogger(__name__)

KNOWN_HOSTS_DIRECTO = os.path.expanduser("~/.ssh/known_hosts_directo")
KNOWN_HOSTS_ANSIBLE = os.path.expanduser("~/.ssh/known_hosts")


def olvidar(host: str) -> "list[str]":
    olvidados: list[str] = []
    for archivo in (KNOWN_HOSTS_DIRECTO, KNOWN_HOSTS_ANSIBLE):
        if not os.path.exists(archivo):
            continue
        try:
            r = subprocess.run(
                ["ssh-keygen", "-R", host, "-f", archivo],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("known_hosts: no se pudo olvidar %s en %s (%s)", host, archivo, exc)
            continue
        if r.returncode != 0:
            logger.warning(
                "known_hosts: ssh-keygen -R %s en %s rc=%s: %s",
                host, archivo, r.returncode, (r.stderr or r.stdout).strip(),
            )
            continue
        try:
            os.unlink(archivo + ".old")
        except OSError:
            pass
        if "updated" in (r.stdout + r.stderr):
            olvidados.append(archivo)
    logger.info("known_hosts: clave de host olvidada host=%s archivos=%s", host, olvidados)
    return olvidados
