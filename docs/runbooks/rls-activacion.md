# Runbook — Activar RLS en un servidor existente

Las políticas de Row-Level Security (sitios, grupos, equipos y auditoría) están
instaladas por las migraciones, pero Postgres **no las aplica** mientras la
aplicación se conecta como `ansiauth`: es el usuario bootstrap del cluster
(`POSTGRES_USER` de la imagen), siempre SUPERUSER, y un superusuario saltea RLS.
Postgres tampoco permite quitarle SUPERUSER al usuario bootstrap.

La solución es que la aplicación se conecte con un rol propio, `ansiauth_app`,
sin SUPERUSER ni BYPASSRLS, dueño de la base y de sus tablas. `ansiauth` queda
como superusuario de mantenimiento.

## Qué cambia

- Cada consulta a `sites`, `device_groups`, `devices` y `audit_logs` la filtra
  también la base, además del filtro de la aplicación.
- Un recurso fuera del alcance del usuario responde como inexistente (404) en
  lugar de 403.
- Los backups (`pg_dump`) **tienen que hacerse como `ansiauth`**. Como
  `ansiauth_app` fallan con `query would be affected by row-level security policy`.

## Prerrequisitos

- El código desplegado incluye la migración `a21msp26_audit_rls` y el
  `install.sh` con `APP_DB_USER`/`APP_DB_PASSWORD` en la plantilla del compose.
- Acceso root al servidor y una ventana de unos minutos: backend, worker y
  beat se reinician.

## Procedimiento

Todos los comandos se corren en el directorio de instalación (donde están
`.env` y `docker-compose.prod.yml`).

### 1. Backup

```bash
docker exec ansiauth-postgres pg_dump -U ansiauth ansiauth > backup-pre-rls-$(date +%F).sql
```

### 2. Crear el rol y transferirle la propiedad

```bash
APP_PW=$(openssl rand -hex 24)
docker exec -i ansiauth-postgres psql -U ansiauth -d ansiauth \
    -v ON_ERROR_STOP=1 -v app_password="$APP_PW" < docs/runbooks/rls-rol-app.sql
```

La salida termina con dos verificaciones: ninguna fila en
`objeto_con_otro_dueno`, y `ansiauth_app | f | f` (sin superusuario ni bypass).

### 3. Configurar la aplicación con el rol nuevo

```bash
cat >> .env <<EOF

# ── RLS: la app conecta con un rol sin SUPERUSER (docs/runbooks/rls-activacion.md) ──
APP_DB_USER=ansiauth_app
APP_DB_PASSWORD=$APP_PW
EOF
```

El `docker-compose.prod.yml` tiene que ser el generado por el `install.sh`
actual (con `${APP_DB_USER:-ansiauth}` en `DATABASE_URL`). Para regenerarlo,
correr de nuevo `install.sh`, que respeta el `.env` existente, o reemplazar a
mano las tres líneas `DATABASE_URL:` de backend, worker y beat por:

```yaml
      DATABASE_URL: postgresql+psycopg://${APP_DB_USER:-ansiauth}:${APP_DB_PASSWORD:-${POSTGRES_PASSWORD}}@db:5432/ansiauth
```

### 4. Reiniciar

```bash
sudo systemctl restart ansiauth-stack
```

### 5. Verificar

```bash
# La app conecta como ansiauth_app:
docker exec ansiauth-postgres psql -U ansiauth -d ansiauth -Atc \
    "SELECT DISTINCT usename FROM pg_stat_activity WHERE datname = 'ansiauth' AND usename <> 'ansiauth';"
# -> ansiauth_app
```

Después, desde la UI:
- Un usuario con permisos en un solo sitio ve solo ese sitio y sus equipos.
- Una sincronización y un cambio de VLAN sobre un equipo del lab terminan bien.
  Así se confirma que el worker opera en contexto de sistema.
- La auditoría muestra los cambios de los equipos del usuario.

## Vuelta atrás

Borrar `APP_DB_USER` y `APP_DB_PASSWORD` del `.env` y reiniciar con
`sudo systemctl restart ansiauth-stack`. La aplicación vuelve a conectarse como
`ansiauth` (superusuario, RLS salteado). No hace falta devolver la propiedad de
los objetos: un superusuario opera igual sobre objetos de otro dueño.
