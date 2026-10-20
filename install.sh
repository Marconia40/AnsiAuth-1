#!/usr/bin/env bash
# install.sh — AnsiAuth VM installer
#
# Instala Docker, Node.js, Caddy, clona el repo, genera secretos, levanta el
# stack con Docker Compose y registra servicios systemd. Pensado para VMs
# Ubuntu 22.04+/24.04 y RHEL/Fedora recientes.
#
# Dos topologías soportadas:
#
#   A) Standalone (default): Caddy bindea :HTTPS_PORT (default 8443) directo al
#      mundo, termina TLS con 'tls internal' (self-signed) o con un cert propio.
#      Backend (8000) y frontend (3000) bindean a 127.0.0.1.
#
#   B) Detrás de reverse proxy externo: hay un nginx/HAProxy/otro adelante que
#      comparte :443 con otras apps y hace SNI passthrough a Caddy en
#      127.0.0.1:HTTPS_PORT. En este modo típicamente:
#        - Se reemplaza 'tls internal' del Caddyfile por 'tls /ruta/cert /ruta/key'.
#        - PUBLIC_URL apunta al puerto público del proxy (típicamente :443, sin
#          puerto explícito en la URL).
#        - SKIP_UFW=1 para no abrir HTTPS_PORT al mundo.
#      Ver docs/DEPLOY_REVERSE_PROXY.md (si existe) para el ejemplo con nginx +
#      ssl_preread.
#
# Re-runs seguros:
#   El script es idempotente y está pensado para re-correrse tras un git pull.
#   Preserva customizaciones locales así no perdés config entre updates:
#     - .env               → se respeta si ya existe.
#     - frontend/.env.local → se respeta si ya existe.
#     - Caddyfile          → se respeta si tiene un 'tls' custom (no 'tls internal').
#   Si necesitás forzar la regeneración, borrá el archivo (o pasá FORCE_REGEN=1).
#
# Uso:
#   curl -sSL https://raw.githubusercontent.com/Marconia40/AnsiAuth-1/main/install.sh | sudo bash
#
# Variables de entorno reconocidas (todas opcionales):
#   INSTALL_DIR   — dónde clonar el repo         (default: /opt/ansiauth)
#   REPO_URL      — URL HTTPS del repo           (default: github.com/Marconia40/AnsiAuth-1.git)
#   BRANCH        — rama a checkoutear           (default: main)
#   NODE_MAJOR    — mayor de Node.js a instalar  (default: 20)
#   RUN_USER      — usuario que correrá node     (default: ansiauth)
#   SKIP_UFW      — 1 para no tocar el firewall  (default: 0)
#   HTTPS_PORT    — puerto donde escucha Caddy   (default: 8443)
#                   En modo B (reverse proxy) sigue siendo el puerto interno.
#   HTTPS_HOST    — hostname/IP público (SAN cert) (default: IP detectada)
#                   Poné el FQDN si tenés DNS interno o público apuntando a
#                   esta VM (ej: HTTPS_HOST=ansiauth.tu-empresa.local). Se usa
#                   para el site block del Caddyfile, CORS_ORIGINS y la
#                   NEXT_PUBLIC_API_URL del frontend. Con hostnames públicos
#                   (registrable domain), 'tls internal' NO funciona a menos
#                   que el hostname esté fijo en el site block — de ahí la
#                   necesidad de esta variable.
#   PUBLIC_URL    — URL que ve el browser (default: https://HTTPS_HOST:HTTPS_PORT)
#                   Setealo cuando estás detrás de un reverse proxy que expone
#                   AnsiAuth en un puerto distinto al de Caddy. Ej:
#                     PUBLIC_URL=https://ansiauth.tu-empresa.local
#                   Se usa para CORS_ORIGINS, NEXT_PUBLIC_API_URL y el resumen
#                   final de credenciales.
#   FORCE_REGEN   — 1 para regenerar Caddyfile y frontend/.env.local aunque ya
#                   existan (backup a .bak). Útil para volver a defaults.

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/ansiauth}"
REPO_URL="${REPO_URL:-https://github.com/Marconia40/AnsiAuth-1.git}"
BRANCH="${BRANCH:-main}"
NODE_MAJOR="${NODE_MAJOR:-20}"
RUN_USER="${RUN_USER:-ansiauth}"
SKIP_UFW="${SKIP_UFW:-0}"
HTTPS_PORT="${HTTPS_PORT:-8443}"
FORCE_REGEN="${FORCE_REGEN:-0}"

CREDS_FILE="/root/ansiauth-credentials.txt"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.prod.yml"
ENV_FILE="$INSTALL_DIR/.env"
FRONTEND_ENV="$INSTALL_DIR/frontend/.env.local"
CADDYFILE="/etc/caddy/Caddyfile"

# ─── Helpers ──────────────────────────────────────────────────────────────────
c_blue=$'\033[1;34m'; c_yellow=$'\033[1;33m'; c_red=$'\033[1;31m'
c_green=$'\033[1;32m'; c_reset=$'\033[0m'
log()  { printf '%s[install]%s %s\n' "$c_blue"   "$c_reset" "$*"; }
warn() { printf '%s[warn]%s %s\n'    "$c_yellow" "$c_reset" "$*" >&2; }
err()  { printf '%s[err]%s %s\n'     "$c_red"    "$c_reset" "$*" >&2; exit 1; }
ok()   { printf '%s[ok]%s %s\n'      "$c_green"  "$c_reset" "$*"; }

on_error() {
    local exit_code=$?
    err "Instalación abortada (exit $exit_code). Revisá los últimos mensajes."
    err "Podés re-correr el script; es idempotente y retomará donde falló."
    exit "$exit_code"
}
trap on_error ERR

[[ $EUID -eq 0 ]] || err "Ejecutar como root: sudo bash install.sh"

# ─── Detectar SO ──────────────────────────────────────────────────────────────
if   command -v apt-get >/dev/null 2>&1; then PKG=apt
elif command -v dnf     >/dev/null 2>&1; then PKG=dnf
else err "Solo se soporta apt (Debian/Ubuntu) y dnf (RHEL/Fedora)."
fi
log "Gestor de paquetes: $PKG"

pkg_install() {
    if [[ "$PKG" == apt ]]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
    else
        dnf install -y "$@"
    fi
}

# ─── Dependencias base ────────────────────────────────────────────────────────
log "Instalando dependencias base..."
if [[ "$PKG" == apt ]]; then
    apt-get update -qq
fi
pkg_install curl ca-certificates git openssl python3 jq

# ─── Docker + compose plugin ──────────────────────────────────────────────────
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker + compose plugin ya presentes ($(docker --version | awk '{print $3}' | tr -d ','))"
else
    log "Instalando Docker via convenience script..."
    curl -fsSL https://get.docker.com | sh
    if [[ "$PKG" == apt ]]; then
        pkg_install docker-compose-plugin
    else
        pkg_install docker-compose-plugin || dnf install -y docker-compose
    fi
    systemctl enable --now docker
fi

# ─── Rotación de logs de Docker ───────────────────────────────────────────────
log "Configurando rotación json-file (max-size=50m, max-file=5)..."
mkdir -p /etc/docker
DAEMON_JSON=/etc/docker/daemon.json
if [[ -s "$DAEMON_JSON" ]]; then
    # Merge preservando otras opciones que el usuario tenga configuradas.
    tmp=$(mktemp)
    jq '. + {"log-driver": "json-file", "log-opts": ((."log-opts" // {}) + {"max-size":"50m","max-file":"5"})}' \
        "$DAEMON_JSON" > "$tmp"
    if ! cmp -s "$tmp" "$DAEMON_JSON"; then
        mv "$tmp" "$DAEMON_JSON"
        systemctl restart docker
        ok "daemon.json actualizado y docker reiniciado"
    else
        rm -f "$tmp"
        ok "daemon.json ya tenía la rotación configurada"
    fi
else
    cat > "$DAEMON_JSON" <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
JSON
    systemctl restart docker
    ok "daemon.json creado y docker reiniciado"
fi

# ─── Node.js ──────────────────────────────────────────────────────────────────
if command -v node >/dev/null 2>&1 && [[ $(node -v | sed 's/^v//' | cut -d. -f1) -ge "$NODE_MAJOR" ]]; then
    ok "Node.js ya presente ($(node -v))"
else
    log "Instalando Node.js $NODE_MAJOR desde NodeSource..."
    if [[ "$PKG" == apt ]]; then
        curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
        pkg_install nodejs
    else
        curl -fsSL "https://rpm.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
        pkg_install nodejs
    fi
fi

# ─── Caddy (reverse proxy + TLS interno) ──────────────────────────────────────
# Termina TLS en :$HTTPS_PORT con cert self-signed emitido por la CA interna
# de Caddy (tls internal). Rutea /api/* al backend y el resto al frontend, así
# el navegador ve un único origen (evita CORS y simplifica cookies).
if command -v caddy >/dev/null 2>&1; then
    ok "Caddy ya presente ($(caddy version | awk '{print $1}'))"
else
    log "Instalando Caddy..."
    if [[ "$PKG" == apt ]]; then
        # Repo oficial de Caddy en Cloudsmith.
        pkg_install debian-keyring debian-archive-keyring apt-transport-https gnupg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            > /etc/apt/sources.list.d/caddy-stable.list
        apt-get update -qq
        pkg_install caddy
    else
        # Fedora trae caddy en repos base; RHEL/Rocky/Alma requieren copr.
        if ! dnf install -y caddy 2>/dev/null; then
            dnf install -y 'dnf-command(copr)'
            dnf copr enable -y @caddy/caddy
            dnf install -y caddy
        fi
    fi
fi

# ─── Usuario del servicio ────────────────────────────────────────────────────
if ! id -u "$RUN_USER" >/dev/null 2>&1; then
    log "Creando usuario del sistema '$RUN_USER'..."
    useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
fi

# ─── Clonar / actualizar repo ─────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Repo ya en $INSTALL_DIR, actualizando..."
    git -C "$INSTALL_DIR" fetch --tags --prune origin
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
else
    log "Clonando $REPO_URL (rama $BRANCH) en $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi
chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR"

# ─── Generar secretos y .env ─────────────────────────────────────────────────
gen_fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }
gen_hex()    { openssl rand -hex 32; }
gen_pw()     { openssl rand -base64 24 | tr -d '\n=+/' | head -c 24; }

HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -z "$HOST_IP" ]] && HOST_IP=$(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2; exit}' | cut -d/ -f1)
[[ -z "$HOST_IP" ]] && HOST_IP="127.0.0.1"

# HTTPS_HOST cae a HOST_IP si el usuario no lo seteó. Cuando difieren (típico
# con hostname DNS público), listamos ambos en el Caddyfile / CORS para que
# accesos por IP también funcionen.
HTTPS_HOST="${HTTPS_HOST:-$HOST_IP}"
if [[ "$HTTPS_HOST" == "$HOST_IP" ]]; then
    CADDY_SITE="$HTTPS_HOST:$HTTPS_PORT"
    CORS_ORIGINS_VAL="https://$HTTPS_HOST:$HTTPS_PORT"
else
    CADDY_SITE="$HTTPS_HOST:$HTTPS_PORT, $HOST_IP:$HTTPS_PORT"
    CORS_ORIGINS_VAL="https://$HTTPS_HOST:$HTTPS_PORT,https://$HOST_IP:$HTTPS_PORT"
fi

# PUBLIC_URL: URL que ve el browser. Prioridades:
#   1) Variable de entorno explícita (override manual).
#   2) NEXT_PUBLIC_API_URL del .env.local existente (respeta customización previa).
#   3) Default: https://HTTPS_HOST:HTTPS_PORT (modo standalone Caddy).
if [[ -z "${PUBLIC_URL:-}" && -f "$FRONTEND_ENV" && "$FORCE_REGEN" != "1" ]]; then
    EXISTING_PUBLIC_URL=$(grep -E '^NEXT_PUBLIC_API_URL=' "$FRONTEND_ENV" 2>/dev/null | cut -d= -f2- || true)
    if [[ -n "$EXISTING_PUBLIC_URL" ]]; then
        PUBLIC_URL="$EXISTING_PUBLIC_URL"
    fi
fi
PUBLIC_URL="${PUBLIC_URL:-https://$HTTPS_HOST:$HTTPS_PORT}"

# Si PUBLIC_URL difiere del default (modo reverse proxy), agregarla a CORS.
DEFAULT_PUBLIC_URL="https://$HTTPS_HOST:$HTTPS_PORT"
if [[ "$PUBLIC_URL" != "$DEFAULT_PUBLIC_URL" && ",$CORS_ORIGINS_VAL," != *",$PUBLIC_URL,"* ]]; then
    CORS_ORIGINS_VAL="$PUBLIC_URL,$CORS_ORIGINS_VAL"
fi

if [[ -f "$ENV_FILE" ]]; then
    ok ".env ya existe en $INSTALL_DIR, respetando valores actuales"
    warn "Si querés regenerar secretos, borrá $ENV_FILE antes de re-correr el script."
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
    # Instalaciones anteriores a la contraseña de Redis: se agrega una sin
    # tocar el resto del archivo.
    if [[ -z "${REDIS_PASSWORD:-}" ]]; then
        REDIS_PASSWORD=$(gen_pw)
        printf '\n# ── Redis ── (agregado por install.sh %s)\nREDIS_PASSWORD=%s\n' \
            "$(date -Iseconds)" "$REDIS_PASSWORD" >> "$ENV_FILE"
        export REDIS_PASSWORD
        ok "REDIS_PASSWORD agregada a $ENV_FILE"
    fi
else
    log "Generando secretos y $ENV_FILE..."
    FERNET_KEY=$(gen_fernet)
    JWT_SECRET_KEY=$(gen_hex)
    BOOTSTRAP_ADMIN_PASSWORD=$(gen_pw)
    POSTGRES_PASSWORD=$(gen_pw)
    REDIS_PASSWORD=$(gen_pw)

    cat > "$ENV_FILE" <<EOF
# Generado automáticamente por install.sh — $(date -Iseconds)
# NO commitear este archivo. Perms 0600.
#
# Este archivo se pasa a los containers via 'env_file:' en el compose,
# así que cualquier variable declarada acá llega directamente a la app.
# Los valores comentados muestran los defaults hardcodeados en config.py;
# descomentá para tunearlos sin tocar el compose.

# ── Secretos (REQUERIDOS) ──
FERNET_KEY=$FERNET_KEY
JWT_SECRET_KEY=$JWT_SECRET_KEY

# ── Bootstrap del super-admin (solo primer arranque) ──
BOOTSTRAP_ADMIN_USER=admin
BOOTSTRAP_ADMIN_PASSWORD=$BOOTSTRAP_ADMIN_PASSWORD

# ── Postgres ──
POSTGRES_PASSWORD=$POSTGRES_PASSWORD

# ── Redis ── (va dentro de REDIS_URL: solo caracteres seguros en una URL)
REDIS_PASSWORD=$REDIS_PASSWORD

# ── App ──
EXECUTION_MODE=mock
LOG_FORMAT=json

# ── Cookies ──
# El stack se sirve por HTTPS en :$HTTPS_PORT (Caddy termina TLS), así que
# las cookies deben ir con Secure. samesite=strict es viable porque frontend
# y backend comparten origen a través del reverse proxy (misma URL).
COOKIE_SECURE=true
COOKIE_SAMESITE=strict

# Con Caddy sirviendo /api/* y / bajo el mismo host:puerto, las llamadas del
# frontend al backend son same-origin y no disparan CORS. Igual dejamos el
# origen listado para peticiones directas o herramientas externas.
CORS_ORIGINS=$CORS_ORIGINS_VAL

# ── Lifetimes de tokens y sesión ──
# Cambiar acá si querés sesiones más largas/cortas sin recompilar la imagen.
# ACCESS_TOKEN_EXPIRE_MINUTES=20
# REFRESH_TOKEN_EXPIRE_MINUTES=240
# REFRESH_TOKEN_IDLE_MINUTES=15         # idle timeout server-side
# SESSION_ABSOLUTE_MAX_HOURS=2          # cap absoluto desde el login
# ELEVATED_TOKEN_EXPIRE_MINUTES=5       # step-up re-auth (destructivo)

# ── Rate limiting (por minuto) ──
# RATE_LIMIT_PER_IP=20
# RATE_LIMIT_PER_USER=200
# RATE_LIMIT_LOGIN=5

# ── Retención y limpieza (ajustar según necesidad de auditoría) ──
AUDIT_RETENTION_DAYS=180
ARTIFACT_RETENTION_DAYS=30
LOGIN_ATTEMPT_RETENTION_DAYS=7
# CLEANUP_INTERVAL_HOURS=6

# ── Observabilidad ──
# METRICS_ENABLED=false   # expone /metrics para Prometheus
EOF
    chmod 600 "$ENV_FILE"
    chown "$RUN_USER:$RUN_USER" "$ENV_FILE"
    ok "Secretos generados"
fi

# ─── docker-compose.prod.yml ─────────────────────────────────────────────────
# El compose se regenera en cada corrida del script — cualquier edición manual
# se pierde. Si tenés customizaciones locales, moverlas a un compose.override.yml
# o al .env.
if [[ -f "$COMPOSE_FILE" ]]; then
    warn "$COMPOSE_FILE existente será sobrescrito (backup en .bak)."
    cp -f "$COMPOSE_FILE" "$COMPOSE_FILE.bak"
fi
log "Escribiendo $COMPOSE_FILE..."
cat > "$COMPOSE_FILE" <<'YAML'
# Compose de producción para AnsiAuth — generado por install.sh.
# Diferencias respecto al docker-compose.yml de dev:
#   - Postgres y Redis bindean a 127.0.0.1 (no expuestos a la red).
#   - Cada service backend/worker/beat carga .env via env_file:, así toda
#     variable declarada en .env llega automáticamente al container.
#   - restart: unless-stopped para sobrevivir reinicios de la VM.
#   - No expone worker/beat como puertos.
#   - Redis con contraseña (REDIS_PASSWORD en .env): quien llega a Redis puede
#     encolar tareas de Celery sin pasar por la API, el RBAC ni la auditoría.
#   - backend/worker/beat corren como el usuario sin privilegios de la imagen
#     (ansiauth, uid 10001), sin capabilities y sin poder ganar privilegios.
#
# 'environment:' se usa sólo para variables que dependen del network interno
# de docker (DATABASE_URL, REDIS_URL con hostnames de container). Compose
# aplica 'environment' encima de 'env_file', así que estos valores ganan
# siempre — cualquier DATABASE_URL en .env es ignorado a propósito.
#
# RLS: con APP_DB_USER/APP_DB_PASSWORD en .env la app conecta con ese rol
# (sin SUPERUSER, creado por docs/runbooks/rls-rol-app.sql) y las políticas
# de Postgres se aplican. Sin ellas usa 'ansiauth', que las saltea.

services:
  redis:
    image: redis:7-alpine
    container_name: ansiauth-redis
    restart: unless-stopped
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:?falta REDIS_PASSWORD en .env}"]
    environment:
      REDISCLI_AUTH: ${REDIS_PASSWORD}
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10

  db:
    image: postgres:16-alpine
    container_name: ansiauth-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ansiauth
      POSTGRES_USER: ansiauth
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - ansiauth-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ansiauth -d ansiauth"]
      interval: 10s
      timeout: 3s
      retries: 10

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: ansiauth-backend
    restart: unless-stopped
    # tini como PID 1: cosecha huérfanos (ansible-connection, ssh) para que
    # no se acumulen zombies y agoten los PIDs del contenedor.
    init: true
    # En memoria: el inventario de Ansible de cada ejecución (/tmp) y la
    # clave privada de la vía SSH directa (device_ssh_keys) se escriben
    # descifrados por un instante; así nunca tocan el disco y desaparecen
    # si el contenedor se cae antes de borrarlos.
    tmpfs:
      - /tmp
      - /app/device_ssh_keys:mode=700,uid=10001,gid=10001
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    volumes:
      # Claves de host aprendidas de los equipos: el worker las aprende y la
      # API las olvida (cambio de host, baja, POST .../forget-host-key).
      - ansiauth-ssh-known-hosts:/home/ansiauth/.ssh
      # Artefactos de ansible-runner: los escribe el worker, los purga la API.
      - ansiauth-ansible-artifacts:/app/ansible/artifacts
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+psycopg://${APP_DB_USER:-ansiauth}:${APP_DB_PASSWORD:-${POSTGRES_PASSWORD}}@db:5432/ansiauth
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    ports:
      # Solo accesible desde el host — el tráfico público entra por Caddy (:8443).
      - "127.0.0.1:8000:8000"

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: ansiauth-worker
    restart: unless-stopped
    # tini como PID 1: cosecha huérfanos (ansible-connection, ssh) para que
    # no se acumulen zombies y agoten los PIDs del contenedor.
    init: true
    # En memoria: el inventario de Ansible de cada ejecución (/tmp) y la
    # clave privada de la vía SSH directa (device_ssh_keys) se escriben
    # descifrados por un instante; así nunca tocan el disco y desaparecen
    # si el contenedor se cae antes de borrarlos.
    tmpfs:
      - /tmp
      - /app/device_ssh_keys:mode=700,uid=10001,gid=10001
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    volumes:
      # Claves de host aprendidas de los equipos: el worker las aprende y la
      # API las olvida (cambio de host, baja, POST .../forget-host-key).
      - ansiauth-ssh-known-hosts:/home/ansiauth/.ssh
      # Artefactos de ansible-runner: los escribe el worker, los purga la API.
      - ansiauth-ansible-artifacts:/app/ansible/artifacts
    command: celery -A app.worker.celery_app worker --loglevel=info --concurrency=4
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+psycopg://${APP_DB_USER:-ansiauth}:${APP_DB_PASSWORD:-${POSTGRES_PASSWORD}}@db:5432/ansiauth
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0

  beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: ansiauth-beat
    restart: unless-stopped
    # tini como PID 1: cosecha huérfanos (ansible-connection, ssh) para que
    # no se acumulen zombies y agoten los PIDs del contenedor.
    init: true
    # El estado de beat va a /tmp: /app es de root y de solo lectura para el
    # usuario de la imagen.
    command: celery -A app.worker.celery_app beat --loglevel=info --schedule /tmp/celerybeat-schedule
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    depends_on:
      redis: {condition: service_healthy}
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+psycopg://${APP_DB_USER:-ansiauth}:${APP_DB_PASSWORD:-${POSTGRES_PASSWORD}}@db:5432/ansiauth
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0

volumes:
  ansiauth-postgres-data:
  ansiauth-ssh-known-hosts:
  ansiauth-ansible-artifacts:
YAML
chown "$RUN_USER:$RUN_USER" "$COMPOSE_FILE"

# ─── Frontend: env + build ────────────────────────────────────────────────────
# NEXT_PUBLIC_API_URL se inlinea en el bundle en tiempo de build, así que si
# alguna vez cambia hay que rebuildear. En re-runs preservamos el archivo si
# ya existe — así deploys detrás de reverse proxy que apuntan a un PUBLIC_URL
# custom no se pisan solos. Para forzar regeneración: FORCE_REGEN=1 o borrar
# el archivo.
if [[ -f "$FRONTEND_ENV" && "$FORCE_REGEN" != "1" ]]; then
    ok "$FRONTEND_ENV ya existe — se preserva (PUBLIC_URL detectada: $PUBLIC_URL)"
    warn "Si querés regenerar apuntando a otro host/puerto, borralo o exportá FORCE_REGEN=1."
else
    if [[ -f "$FRONTEND_ENV" ]]; then
        cp -f "$FRONTEND_ENV" "$FRONTEND_ENV.bak"
    fi
    log "Escribiendo $FRONTEND_ENV..."
    cat > "$FRONTEND_ENV" <<EOF
NEXT_PUBLIC_API_URL=$PUBLIC_URL
EOF
    chown "$RUN_USER:$RUN_USER" "$FRONTEND_ENV"
fi

log "Instalando dependencias y compilando frontend (esto tarda unos minutos)..."
sudo -u "$RUN_USER" bash -lc "cd '$INSTALL_DIR/frontend' && npm ci --no-audit --no-fund && npm run build"
ok "Frontend compilado"

# ─── systemd: stack backend (docker compose) ─────────────────────────────────
log "Registrando servicio systemd ansiauth-stack.service..."
cat > /etc/systemd/system/ansiauth-stack.service <<EOF
[Unit]
Description=AnsiAuth backend stack (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d
ExecStop=/usr/bin/docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

# ─── systemd: frontend Next.js ───────────────────────────────────────────────
log "Registrando servicio systemd ansiauth-frontend.service..."
cat > /etc/systemd/system/ansiauth-frontend.service <<EOF
[Unit]
Description=AnsiAuth frontend (Next.js)
After=network-online.target ansiauth-stack.service
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$INSTALL_DIR/frontend
Environment=NODE_ENV=production
Environment=PORT=3000
# Bindea a loopback: el tráfico público entra por Caddy (:$HTTPS_PORT) y
# proxya a 127.0.0.1:3000.
Environment=HOSTNAME=127.0.0.1
ExecStart=/usr/bin/npm run start
Restart=always
RestartSec=5

# stdout/stderr → journald, con rotación gobernada por journald.conf del sistema.
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ansiauth-stack.service ansiauth-frontend.service >/dev/null

# ─── Caddyfile + service ─────────────────────────────────────────────────────
# Preservación en re-runs: si el Caddyfile existente NO tiene 'tls internal'
# significa que fue customizado (probablemente para usar un cert emitido por
# la CA de tu organización o para agregar directivas como 'protocols h1' en
# modo reverse-proxy). En ese caso NO lo regeneramos, para no pisar tu config.
# Para forzar regeneración a defaults, exportá FORCE_REGEN=1 o borrá el archivo.
CADDY_REGEN=1
if [[ -f "$CADDYFILE" && "$FORCE_REGEN" != "1" ]]; then
    # Sólo la directiva activa, no los comentarios: el Caddyfile generado
    # menciona 'tls internal' en su encabezado, y uno personalizado que los
    # conservó (con 'tls /ruta/cert /ruta/key') se pisaba igual.
    if ! grep -Eq '^[[:space:]]*tls[[:space:]]+internal' "$CADDYFILE"; then
        ok "$CADDYFILE customizado (no tiene 'tls internal') — se preserva."
        warn "Si necesitás regenerarlo a defaults, exportá FORCE_REGEN=1 o borrá $CADDYFILE."
        CADDY_REGEN=0
    fi
fi

if [[ "$CADDY_REGEN" == "1" ]]; then
if [[ -f "$CADDYFILE" ]]; then
    # Con fecha: un .bak fijo se pisaría en la corrida siguiente y se perdería
    # la versión anterior.
    cp -f "$CADDYFILE" "$CADDYFILE.bak.$(date +%Y%m%d-%H%M%S)"
fi
log "Escribiendo $CADDYFILE (HTTPS :$HTTPS_PORT con tls internal)..."
cat > "$CADDYFILE" <<EOF
# Caddyfile — generado por install.sh
#
# Sirve $CADDY_SITE con TLS interno de Caddy y rutea por path:
#   /api/*  → backend  (FastAPI en 127.0.0.1:8000)
#   resto   → frontend (Next.js en 127.0.0.1:3000)
#
# 'tls internal' hace que Caddy emita el cert desde su CA local. La root CA
# vive en /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
# — importala en el trust store del cliente para eliminar el warning del
# browser.
#
# IMPORTANTE: los subjects (hostname/IP) están explícitos en el site block
# porque 'tls internal' con bare ':port' rechaza el handshake para dominios
# públicos (public suffix) — Caddy no emite on-demand para nombres que no
# controla. Fijándolos acá, la emisión ocurre al arrancar y los clientes
# solo ven el warning normal de self-signed (con opción de continuar).

{
	# Redirecciones auto de HTTP→HTTPS deshabilitadas: no exponemos :80.
	auto_https disable_redirects
}

$CADDY_SITE {
	tls internal

	# Compresión estándar.
	encode gzip

	# Rutas del backend: la API bajo /api/v1/*, health/metrics, y las docs de
	# FastAPI (/docs = Swagger UI, /redoc = ReDoc, /openapi.json = schema).
	# Las docs quedan expuestas por HTTPS porque es una app interna detrás de
	# login — si algún día se hace pública, deshabilitarlas en FastAPI con
	# docs_url=None / redoc_url=None.
	@backend path /api/* /health /metrics /docs /redoc /openapi.json
	handle @backend {
		reverse_proxy 127.0.0.1:8000
	}

	# Todo lo demás (assets, SSR, HMR/WS en dev) al frontend.
	handle {
		reverse_proxy 127.0.0.1:3000
	}

	# Logs → journald (systemd-cat) via el propio caddy.service.
	log {
		output stderr
		format console
	}
}
EOF
fi  # fin de CADDY_REGEN

# Validación temprana: si el Caddyfile es inválido, mejor abortar antes de
# tocar systemd que dejar el service en failed loop.
if ! caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
    err "Caddyfile inválido — revisar $CADDYFILE"
fi

log "Habilitando caddy.service..."
systemctl enable caddy >/dev/null
# reload es idempotente (arranca si estaba down, recarga config si estaba up).
systemctl restart caddy
ok "Caddy activo en :$HTTPS_PORT"

# ─── Firewall (UFW en Debian/Ubuntu) ─────────────────────────────────────────
# Solo agregamos reglas de forma idempotente. NO reseteamos el ruleset ni
# cambiamos las policies default — eso borraría reglas que el usuario haya
# configurado a mano (VPN, monitoring, backups, etc). Si UFW está inactivo,
# tampoco lo forzamos a activarse: dejamos las reglas cargadas y avisamos.
if [[ "$SKIP_UFW" != "1" && "$PKG" == "apt" ]]; then
    log "UFW: agregando reglas SSH + $HTTPS_PORT/tcp (sin tocar reglas existentes)..."
    pkg_install ufw
    ufw allow OpenSSH >/dev/null
    ufw allow "$HTTPS_PORT/tcp" comment 'AnsiAuth HTTPS (Caddy)' >/dev/null
    if ufw status 2>/dev/null | grep -q "Status: active"; then
        ok "UFW activo — reglas aplicadas"
    else
        warn "UFW está inactivo — las reglas quedaron cargadas pero no se aplican."
        warn "Para activarlo (revisá antes que OpenSSH esté permitido): sudo ufw enable"
    fi
elif [[ "$SKIP_UFW" != "1" ]]; then
    warn "Saltando UFW: no está en apt-land. Abrí manualmente $HTTPS_PORT/tcp."
fi

# ─── Build de imágenes ───────────────────────────────────────────────────────
# Se hace acá y no dentro del ExecStart de systemd para que:
#   - el primer arranque no tarde 5 min extra bloqueando el service manager;
#   - en re-corridas del install.sh (después de git pull) el código nuevo
#     entre a la imagen sin depender de un 'docker compose build' manual.
log "Building/actualizando imágenes docker (esto puede tardar varios minutos)..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build --pull

# ─── Arrancar ─────────────────────────────────────────────────────────────────
# 'docker compose up -d' es idempotente y recrea sólo los containers cuya
# imagen cambió — más quirúrgico que un 'systemctl restart' que hace down+up
# completo. systemctl start después sólo marca el service como activo para
# que persista tras reinicios de la VM.
log "Aplicando cambios al stack (up -d)..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

log "Registrando stack en systemd para arranque automático..."
systemctl start ansiauth-stack.service || true

log "Esperando a que /health responda (hasta 120s)..."
for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
        ok "Backend arriba (después de ${i}x2s)"
        break
    fi
    sleep 2
    if [[ $i -eq 60 ]]; then
        warn "El backend no respondió a /health en 120s."
        warn "Revisá: journalctl -u ansiauth-stack -e  y  docker compose -f $COMPOSE_FILE logs"
    fi
done

log "Arrancando frontend..."
# restart y no start: en una re-corrida el servicio ya está activo y 'start'
# no hace nada -- seguiría sirviendo el build anterior aunque 'npm run build'
# ya haya generado el nuevo.
systemctl restart ansiauth-frontend.service
sleep 3
if systemctl is-active --quiet ansiauth-frontend.service; then
    ok "Frontend activo"
else
    warn "Frontend no arrancó. Revisá: journalctl -u ansiauth-frontend -e"
fi

# ─── Verificación final por HTTPS ────────────────────────────────────────────
# -k porque el cert es self-signed (tls internal). Si esto falla, el problema
# está en Caddy o en el bind loopback de backend/frontend.
log "Verificando que la app responde por HTTPS..."
if curl -kfsS "https://127.0.0.1:$HTTPS_PORT/health" >/dev/null 2>&1; then
    ok "Caddy → backend OK (https://127.0.0.1:$HTTPS_PORT/health)"
else
    warn "No responde /health por Caddy. Revisá: journalctl -u caddy -e"
fi

CADDY_ROOT_CA="/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"

# ─── Guardar credenciales ─────────────────────────────────────────────────────
log "Guardando credenciales en $CREDS_FILE (0600)..."
# Recargar el .env por si venía preexistente y no las teníamos en variables.
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
cat > "$CREDS_FILE" <<EOF
AnsiAuth — credenciales generadas $(date -Iseconds)
======================================================
URL app (HTTPS):    $PUBLIC_URL
URL API (HTTPS):    $PUBLIC_URL/api/v1

Super-admin inicial:
  usuario:          ${BOOTSTRAP_ADMIN_USER:-admin}
  password:         ${BOOTSTRAP_ADMIN_PASSWORD}

Postgres (solo local, 127.0.0.1:5432):
  usuario:          ansiauth
  password:         ${POSTGRES_PASSWORD}

Archivos importantes:
  .env:             $ENV_FILE
  compose prod:     $COMPOSE_FILE
  Caddyfile:        $CADDYFILE
  daemon.json:      /etc/docker/daemon.json

Certificado TLS (self-signed emitido por Caddy):
  root CA:          $CADDY_ROOT_CA
  Para eliminar el warning del browser en cada cliente:
    1) Copiar ese archivo a la máquina del usuario.
    2) Importarlo en el trust store del sistema o del browser.
       — Windows: certmgr.msc → "Trusted Root Certification Authorities".
       — macOS:   Keychain Access → System → import → marcar "Always Trust".
       — Linux:   cp root.crt /usr/local/share/ca-certificates/ &&
                  update-ca-certificates.
    3) En corporate: IT puede empujar la root CA via GPO/MDM.

Modo de ejecución: EXECUTION_MODE=${EXECUTION_MODE:-mock}
  * mock  → no se dispara ningún playbook real (default, seguro para probar).
  * real  → los equipos se dan de alta desde la web o la API (no hay
            inventory.ini); setear EXECUTION_MODE=real en $ENV_FILE y
            reiniciar el stack.

Gestión:
  systemctl status ansiauth-stack ansiauth-frontend caddy
  systemctl restart ansiauth-stack
  systemctl reload caddy       # tras editar $CADDYFILE
  journalctl -u ansiauth-stack -f
  journalctl -u ansiauth-frontend -f
  journalctl -u caddy -f
  docker compose -f $COMPOSE_FILE logs -f backend

Actualizar a la última versión de $BRANCH:
  sudo bash $INSTALL_DIR/install.sh
  # (esto hace git pull, rebuildea imágenes docker y recrea containers)
EOF
chmod 600 "$CREDS_FILE"

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo
ok "══════════════════════════════════════════════════════════════════"
ok "  Instalación completa."
ok "══════════════════════════════════════════════════════════════════"
echo
echo "  URL app:        $PUBLIC_URL"
echo "  Usuario admin:  ${BOOTSTRAP_ADMIN_USER:-admin}"
echo "  Password admin: ${BOOTSTRAP_ADMIN_PASSWORD}"
echo
echo "  Credenciales guardadas en:  $CREDS_FILE"
echo "  (perms 0600 — solo root puede leerlas)"
echo
warn "El cert es self-signed (Caddy tls internal). La primera vez el browser"
warn "va a mostrar warning — click 'Continuar' o importá la root CA:"
warn "  $CADDY_ROOT_CA"
echo
if [[ "${EXECUTION_MODE:-mock}" != "real" ]]; then
    warn "EXECUTION_MODE=mock: no se dispararán playbooks reales."
    warn "Para automatizar dispositivos, cambiá EXECUTION_MODE=real en $ENV_FILE"
    warn "y reiniciá:"
    warn "  systemctl restart ansiauth-stack"
    echo
fi
