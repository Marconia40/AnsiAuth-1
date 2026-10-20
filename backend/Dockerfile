# Image for the AnsiAuth backend (API, Celery worker and Celery Beat).
# The schema is owned by Alembic, so the entrypoint runs `alembic upgrade head`
# before starting uvicorn.

# ── Build stage: compilers and headers stay here, not in the final image ──
FROM python:3.12-slim AS builder

# Build toolchain for wheels that may need compiling (cryptography,
# ansible-core source distributions).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Ansible Galaxy collections used by the playbooks, installed in a system path
# so the unprivileged runtime user can read them.
RUN ansible-galaxy collection install -p /usr/share/ansible/collections \
        cisco.ios \
        ansible.netcommon \
        community.network

# ── Final image ──
FROM python:3.12-slim AS base

# Runtime system packages:
#   - sshpass: password authentication for ansible-runner
#   - openssh-client: ssh / ssh-agent / ssh-keygen for devices that use key
#     authentication (app.services.ssh_direct_service) and for host key
#     management (app.services.known_hosts)
#   - libpq5: PostgreSQL client library for psycopg
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        sshpass \
        openssh-client \
        libpq5 \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /usr/share/ansible/collections /usr/share/ansible/collections
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

# Unprivileged user. It must exist in /etc/passwd because OpenSSH refuses to
# run for a uid without an entry. Its home keeps ~/.ansible (persistent
# connection sockets) and ~/.ssh (learned host keys, a volume in compose).
RUN groupadd --gid 10001 ansiauth \
 && useradd --uid 10001 --gid ansiauth --create-home --home-dir /home/ansiauth \
        --shell /usr/sbin/nologin ansiauth \
 && install -d -m 700 -o ansiauth -g ansiauth /home/ansiauth/.ssh

WORKDIR /app

# Network devices with legacy SSH algorithms (diffie-hellman-group14-sha1 KEX,
# ssh-rsa host keys) are reached through paramiko; ansible-pylibssh rejects
# those algorithms by default, so it is intentionally not installed.

# Project source, owned by root and read-only for the app user. Only the
# ansible-runner artifacts and the key directory (tmpfs in compose) are
# writable. .dockerignore keeps .env files, artifacts and local databases out.
COPY . /app
# a+rX: readable by the app user even if the checkout used a restrictive umask.
RUN chmod -R a+rX /app \
 && install -d -m 755 -o ansiauth -g ansiauth /app/ansible/artifacts \
 && install -d -m 700 -o ansiauth -g ansiauth /app/device_ssh_keys

USER ansiauth

# uvicorn listens on 0.0.0.0:8000 inside the container; compose publishes it.
EXPOSE 8000

# Run migrations, then start the API (no --reload in the image).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
