<p align="right"><b>Español</b> · <a href="README.en.md">English</a></p>

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/AnsiAuth_Logo_Color_Tight.svg">
  <img src="frontend/public/brand/AnsiAuth_Logo_Color_Tight.svg" alt="AnsiAuth" width="480">
</picture>

<p><b>Plataforma de Automatización de Red Multivendor</b></p>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Ansible](https://img.shields.io/badge/Ansible-13-EE0000?logo=ansible&logoColor=white)
[![Licencia](https://img.shields.io/badge/licencia-PolyForm%20Noncommercial%201.0.0-lightgrey)](LICENSE)

</div>

---

> **Contexto académico**
>
> | | |
> |---|---|
> | **Título de la tesis** | AnsiAuth |
> | **Autores** | Endrek, Marco · Martin, Tomas |
> | **Director/a** | Solinas, Miguel Angel |
> | **Codirector/a** | Bettucci, Marcos |
> | **Carrera** | Ingenieria en Computacion |
> | **Facultad y universidad** | FCEFyN - UNC |
> | **Año** | 2026 |

## Índice

- [Resumen](#resumen)
- [Capturas y demo](#capturas-y-demo)
- [Funcionalidades principales](#funcionalidades-principales)
- [Tecnologías utilizadas](#tecnologías-utilizadas)
- [Arquitectura](#arquitectura)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Tests](#tests)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Documentación de la tesis](#documentación-de-la-tesis)
- [Autores, agradecimientos y licencia](#autores-agradecimientos-y-licencia)

## Resumen

### Problema

Configurar equipos de red de distintos fabricantes (Cisco, Huawei) suele hacerse
equipo por equipo, por SSH y con la sintaxis de línea de comandos propia de cada
uno. Ese trabajo manual es propenso a errores, depende de que cada operador conozca
la CLI de cada fabricante, no deja un registro centralizado de quién cambió qué y
no permite delegar permisos con distinto alcance (por sitio o por grupo de equipos).
Un cambio que falla a mitad de camino puede dejar el equipo en un estado intermedio
sin que nadie lo revierta.

### Objetivo general

Desarrollar una plataforma de administración centralizada para la gestión de switches
multivendor desde una interfaz única, que abstraiga la complejidad sintáctica de cada
fabricante y reduzca la intervención manual, garantizando que las operaciones sobre la red
sean idempotentes, trazables y reversibles.

### Objetivos específicos

- Analizar las estrategias de automatización de red y relevar las herramientas de gestión
existentes, para fundamentar la selección del motor de automatización y del stack
tecnológico.
- Diseñar una arquitectura modular que permita incorporar nuevos recursos sin
modificar la lógica central de los cambios.
- Abstraer las diferencias de sintaxis entre fabricantes, de modo que incorporar uno
nuevo no requiera modificar el resto del sistema.
- Implementar las operaciones sobre los recursos de red principales: VLAN, puertos
físicos, interfaces virtuales (SVI) y configuración global del dispositivo.
- Incorporar una ejecución asíncrona de los cambios, con reintentos ante fallas
transitorias y rollback ante fallas permanentes.
- Implementar un control de acceso basado en roles (RBAC) y un registro de auditoría
que permita reconstruir qué cambio se aplicó, sobre qué equipo, en qué momento y
por qué usuario [31].
- Organizar los equipos en sitios y grupos, con permisos por alcance y operaciones
sobre conjuntos de equipos.
- Construir una interfaz web que permita operar el sistema y consultar el estado de la
red sin recurrir a la CLI de cada equipo.
- Validar la plataforma de manera incremental en un laboratorio virtualizado, un
entorno físico dedicado y equipos en producción, evaluando su desempeño e
incorporando mitigaciones ante las fallas detectadas.

## Capturas y demo

<!-- IMAGEN: pantalla de inicio de sesión. PNG, ~1280 px de ancho -->
![Inicio de sesión](docs/images/captura-login.jpeg)

<!-- IMAGEN: tablero de un sitio con el resumen de equipos y las pestañas VLAN / PORTS / VIRTUAL-INTERFACES / GLOBAL-CONFIG. PNG, ~1280 px de ancho -->
![Tablero](docs/images/captura-panel.jpeg)

<!-- IMAGEN: edición de puertos de un equipo (selección de varios puertos y panel de cambios). PNG, ~1280 px de ancho -->
![Edición de puertos](docs/images/captura-puertos.jpeg)

<!-- IMAGEN: listado de trabajos con su estado y el detalle de uno (comandos, rollback). PNG, ~1280 px de ancho -->
![Trabajos](docs/images/captura-trabajos.jpeg)

## Funcionalidades principales

- **Autenticación y sesiones**: token de acceso JWT de corta duración y refresh token rotativo en una cookie HttpOnly, cierre por inactividad y duración máxima de sesión, re-autenticación para operaciones destructivas, bloqueo por intentos fallidos, límite de peticiones y gestión de sesiones activas.
- **Organización multi-sitio**: jerarquía Sitio → Grupo → Equipo. Permisos `observer`, `operator` y `admin` asignados por sitio o por grupo, más el rol de sistema `super-admin`; el rol efectivo es el máximo de los permisos que aplican. Opcionalmente, Row-Level Security de PostgreSQL ([runbook](docs/runbooks/rls-activacion.md)).
- **Inventario**: alta de equipos Cisco IOS / IOS-XE (`cisco_ios`) y Huawei VRP (`huawei_vrp`) con contraseña o clave privada, cifradas con Fernet; movimiento entre grupos y sitios; la clave de host SSH se guarda en la primera conexión y se exige en las siguientes.
- **VLANs**: crear, renombrar y eliminar en uno o varios equipos a la vez, y en lote.
- **Puertos**: modo access o trunk, VLAN de acceso, VLANs permitidas, descripción, estado administrativo, PoE, storm-control y restablecimiento a valores por defecto, editando varios puertos de un equipo en un solo trabajo.
- **Interfaces virtuales (SVI)**: direcciones IPv4 primaria y secundarias, IPv6, ACL, DHCP relay, descripción y estado.
- **Configuración global**: hostname, NTP, DNS, servidores de log, SNMP, rutas estáticas y ACLs; consulta de running-config, versión, logs y tablas ARP/MAC, con búsqueda de una MAC en vivo.
- **Trabajos asíncronos**: cada cambio se ejecuta como un trabajo en un worker Celery, con bloqueo por equipo, captura del estado previo, reintentos ante errores transitorios, rollback si el cambio falla, cancelación y seguimiento en vivo desde la interfaz.
- **Guardado de configuración** en la memoria no volátil del equipo.
- **Auditoría** de solo inserción de cada acción, con filtros y retención configurable.
- **Modo `mock`** para desarrollar y probar sin equipos reales.
- **Operación**: health check, logs en JSON, métricas Prometheus opcionales e instalador para servidores Linux ([`install.sh`](install.sh)).

## Tecnologías utilizadas

| Área | Tecnología | Versión |
|---|---|---|
| **Frontend** | Next.js (App Router) | 16.2.6 |
| | React | 19.2.4 |
| | TypeScript | 5 (5.9.3) |
| | Tailwind CSS | 4 (4.3.0) |
| | TanStack Query · Axios | 5.100.11 · 1.16.1 |
| **Backend** | Python | 3.12 |
| | FastAPI · Starlette · Uvicorn | 0.136.0 · 1.0.0 · 0.44.0 |
| | Pydantic · pydantic-settings | 2.13.3 · 2.x |
| | SQLAlchemy · Alembic | 2.x · ≥ 1.13 |
| | Celery (worker y beat) | 5.x |
| | PyJWT · passlib · cryptography (Fernet) | 2.x · 1.7 · 46.0.7 |
| **Automatización de red** | Ansible · ansible-core | 13.5.0 · 2.20.4 |
| | ansible-runner | 2.4.3 |
| | Colecciones `cisco.ios`, `ansible.netcommon`, `community.network` | la última de Ansible Galaxy |
| | Paramiko (transporte `network_cli`) · OpenSSH (SSH directo con clave) | 2.x · el del sistema |
| **Base de datos y mensajería** | PostgreSQL (psycopg 3) | 16 |
| | Redis (broker de Celery y bloqueos por equipo) | 7 |
| **Infraestructura** | Docker y Docker Compose v2 | — |
| | Caddy (proxy inverso y TLS en producción) | la del repositorio oficial |
| | Node.js (frontend en producción) | 20 |
| **Calidad** | pytest · httpx | 7.4.0 · 0.28.1 |
| | ESLint | 9 |

Las versiones exactas están en [`backend/requirements.txt`](backend/requirements.txt) y [`frontend/package.json`](frontend/package.json). Entre paréntesis figura la versión resuelta cuando el archivo declara un rango.

## Arquitectura

El sistema separa la interfaz web, la API y la ejecución de los cambios:

- **Frontend (Next.js)**: interfaz web que consume la API REST `/api/v1`. Guarda el token de acceso en memoria y renueva la sesión con el refresh token de la cookie.
- **Backend (FastAPI)**: valida, autoriza según el alcance del usuario (sitio o grupo), registra la auditoría y encola cada cambio como un trabajo: los cambios nunca se aplican dentro de la petición HTTP.
- **Worker (Celery)**: toma los trabajos de Redis. El orquestador bloquea el equipo, captura su estado, aplica el cambio, reintenta ante fallas transitorias y revierte si falla. Llega a los equipos con `ansible-runner` (autenticación por contraseña) o con OpenSSH (autenticación por clave).
- **Drivers por fabricante**: cada fabricante implementa la misma interfaz (`VendorDriver`), con sus comandos y parsers. Un registro de plugins elige el driver según el campo `vendor` del equipo, así que agregar un fabricante no cambia el orquestador.
- **Celery Beat**: tareas periódicas, como la recuperación de trabajos huérfanos.
- **PostgreSQL**: usuarios, permisos, sitios, grupos, equipos (credenciales cifradas), trabajos, estado leído de los equipos y auditoría.
- **Redis**: broker de Celery, bloqueos por equipo, semáforo global de sesiones SSH y ritmo de comandos por equipo.
- **Caddy** (solo producción): termina TLS y sirve `/api/*` y la interfaz desde el mismo origen.

```mermaid
flowchart LR
    U["Usuario<br/>(navegador)"] -->|HTTPS| C["Caddy<br/>proxy inverso + TLS<br/>(producción)"]
    C -->|"/"| F["Frontend<br/>Next.js"]
    C -->|"/api/*"| B["Backend API<br/>FastAPI"]
    F -.->|"REST /api/v1 + JWT"| B
    B --> P[("PostgreSQL 16")]
    B -->|encola trabajos| R[("Redis 7")]
    BT["Celery Beat"] -->|tareas periódicas| R
    R --> W["Worker Celery<br/>orquestador + drivers"]
    W --> P
    W -->|"ansible-runner<br/>(contraseña)"| D["Switches<br/>Cisco IOS / IOS-XE<br/>Huawei VRP"]
    W -->|"OpenSSH<br/>(clave privada)"| D
```

## Requisitos previos

| Herramienta | Versión | Para qué |
|---|---|---|
| Git | cualquiera reciente | Clonar el repositorio |
| Docker Engine + plugin Docker Compose v2 | Compose v2 (verificado con 5.6.0) | Opción A y servicios `db` / `redis` de la opción B |
| Node.js + npm | Node ≥ 20.9 (requisito de Next.js 16) | Frontend |
| Python | 3.12 (el de la imagen Docker; también verificado con 3.14) | Solo la opción B y los tests |
| OpenSSH client y `sshpass` | los del sistema | Solo en modo `real` fuera de Docker |

Puertos que se usan en desarrollo: `3000` (frontend), `8000` (API), `5432` (PostgreSQL) y `6379` (Redis), estos dos últimos solo en `127.0.0.1`.

> **Nota:** el `docker-compose.yml` usa la opción `uid=` en los `tmpfs`, que Docker acepta y Podman rechaza. Se recomienda usar Docker.

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/Marconia40/AnsiAuth-1.git ansiauth
cd ansiauth
```

### Opción A: con Docker (recomendada)

Levanta PostgreSQL, Redis, la API, el worker y Celery Beat. Las migraciones de la base (`alembic upgrade head`) corren solas al iniciar el contenedor de la API.

```bash
# 1. Variables de docker compose: copiar la plantilla y generar las dos claves
cp .env.example .env
sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')|" .env
sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')|" .env
# Editar .env y cambiar BOOTSTRAP_ADMIN_PASSWORD (mínimo 12 caracteres)

# 2. Construir y levantar el stack
docker compose up -d --build

# 3. Comprobar que la API responde
curl http://localhost:8000/health
```

Después, levantar el frontend:

```bash
cd frontend
cp .env.example .env.local    # NEXT_PUBLIC_API_URL=http://localhost:8000
npm ci
npm run dev                   # http://localhost:3000
```

Comandos útiles: `docker compose logs -f backend worker` (ver logs), `docker compose down` (detener, conserva los datos) y `docker compose down -v` (detener y borrar la base).

### Opción B: backend local (sin Docker para la API)

PostgreSQL y Redis siguen corriendo con Docker; la API y el worker corren en el equipo, con un entorno virtual.

```bash
# 1. Base de datos y Redis
docker compose up -d db redis

# 2. Entorno virtual y dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# 3. Configuración del backend
cp backend/.env.example backend/.env
sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')|" backend/.env
sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')|" backend/.env

# 4. Migraciones y API
cd backend
alembic upgrade head
uvicorn app.main:app --reload            # http://localhost:8000
```

En otra terminal, con el entorno virtual activado, levantar el worker que ejecuta los trabajos:

```bash
cd backend
celery -A app.worker.celery_app worker --loglevel=info
```

El frontend se levanta igual que en la opción A.

> **Importante:** si las opciones A y B usan la misma base, `FERNET_KEY` tiene que ser la misma en `.env` y en `backend/.env`. Si no, el worker no puede descifrar las credenciales de los equipos que dio de alta el otro backend (`InvalidToken`).

Para trabajar contra equipos reales fuera de Docker (`EXECUTION_MODE=real`), instalar además las colecciones de Ansible:

```bash
ansible-galaxy collection install cisco.ios ansible.netcommon community.network
```

### Datos iniciales

No hay datos de prueba precargados. Las migraciones crean el sitio de sistema **Base Infrastructure** con su grupo **Default**. En el primer arranque, la API crea el usuario `admin` (super-admin) con la contraseña de `BOOTSTRAP_ADMIN_PASSWORD`.

### Instalación en un servidor (producción)

[`install.sh`](install.sh) instala Docker, Node.js y Caddy en Ubuntu 22.04/24.04 o RHEL/Fedora. Además clona el repositorio en `/opt/ansiauth`, genera secretos aleatorios, levanta el stack con un compose de producción y registra los servicios de systemd. Por defecto sirve la aplicación por HTTPS en el puerto `8443`.

```bash
sudo bash install.sh
```

Las variables que acepta (`HTTPS_HOST`, `HTTPS_PORT`, `PUBLIC_URL`, `BRANCH`, `SKIP_UFW`, etc.) están documentadas al comienzo del script. Al terminar, las credenciales iniciales quedan en `/root/ansiauth-credentials.txt`. Para TLS con un certificado propio, ver [`docs/deployment/tls-setup.md`](docs/deployment/tls-setup.md).

## Uso

1. Abrir **http://localhost:3000** e iniciar sesión con `admin` y la contraseña de `BOOTSTRAP_ADMIN_PASSWORD`. No hay otros usuarios de prueba: los demás se crean desde la sección **Users**.
2. En **Inventory**, dar de alta un equipo dentro del sitio *Base Infrastructure*, o crear antes un sitio propio con **+ New site** en el tablero de la organización. En modo `mock` (el predeterminado) cualquier IP sirve, porque no se abre ninguna conexión.
3. Navegar al sitio, al grupo o al equipo y usar las pestañas **VLAN**, **PORTS**, **VIRTUAL-INTERFACES** y **GLOBAL-CONFIG**. Cada cambio genera un trabajo que se sigue en **Jobs** y queda registrado en **Audit**.

La API está documentada con Swagger en **http://localhost:8000/docs**. Ejemplo con `curl`:

```bash
# Iniciar sesión y guardar el token de acceso
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  --data-urlencode "username=admin" --data-urlencode "password=<BOOTSTRAP_ADMIN_PASSWORD>" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Dar de alta un equipo en el sitio 1 (Base Infrastructure)
curl -s -X POST http://localhost:8000/api/v1/devices/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"sw-demo-01","host":"192.0.2.10","vendor":"cisco_ios","username":"admin","password":"demo-password","site_id":1}'

# Crear la VLAN 100 en ese equipo: responde con el job_id de cada equipo
curl -s -X POST http://localhost:8000/api/v1/vlans/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"vlan_id":100,"name":"DEMO","devices":["sw-demo-01"]}'

# Consultar el estado del trabajo
curl -s http://localhost:8000/api/v1/jobs/<job_id> -H "Authorization: Bearer $TOKEN"
```

Para operar equipos reales, poner `EXECUTION_MODE=real` en el `.env` correspondiente y reiniciar la API y el worker. Todas las variables están explicadas en [`.env.example`](.env.example) y [`backend/.env.example`](backend/.env.example).

## Tests

La suite del backend (1427 tests, pytest) corre contra una base PostgreSQL **dedicada**. Por seguridad, `conftest.py` se niega a usar una base cuyo nombre no contenga `test`, porque al empezar borra su esquema. Necesita un `backend/.env` con una `FERNET_KEY` válida (paso 3 de la opción B).

```bash
# Base de pruebas (solo la primera vez)
docker compose up -d db
docker compose exec db createdb -U ansiauth ansiauth_test

# Correr la suite en modo mock
cd backend
EXECUTION_MODE=mock python -m pytest
```

Por defecto se conecta a `postgresql+psycopg://ansiauth:ansiauth_dev_password@localhost:5432/ansiauth_test`. Para usar otra base de pruebas, definir `DATABASE_URL` antes de `pytest`.

Frontend (chequeo de tipos y lint):

```bash
cd frontend
npx tsc --noEmit
npm run lint
```

## Estructura del proyecto

```text
ansiauth/
├── backend/                  # API REST, worker y automatización de red
│   ├── app/
│   │   ├── api/              # Routers FastAPI (/api/v1/...)
│   │   ├── core/             # Configuración, seguridad JWT, alcance y roles, RLS, TLS
│   │   ├── db/               # Sesión y modelos ORM de SQLAlchemy, guarda de auditoría
│   │   ├── models/           # Modelos de dominio (equipo, puerto, SVI, trabajo, auditoría…)
│   │   ├── repositories/     # Acceso a datos
│   │   ├── schemas/          # Esquemas Pydantic de entrada y salida
│   │   ├── services/         # Orquestador, cola de trabajos, sincronización, auditoría
│   │   │   ├── parsers/      # Lectura de salidas de CLI (VLAN, puertos, SVI, config global, ARP/MAC)
│   │   │   └── vendors/      # Drivers Cisco IOS y Huawei VRP, y driver mock
│   │   ├── main.py           # Punto de entrada de la API
│   │   ├── worker.py         # Aplicación Celery y agenda de Beat
│   │   └── tasks.py          # Tareas Celery
│   ├── ansible/              # ansible.cfg y playbooks por fabricante
│   ├── migrations/           # Migraciones de Alembic
│   ├── tests/                # Suite de pytest
│   ├── Dockerfile            # Imagen de la API, el worker y Beat
│   ├── requirements.txt
│   └── start.py              # Lanzador de uvicorn con TLS opcional
├── frontend/                 # Interfaz web (Next.js)
│   ├── public/brand/         # Logos
│   └── src/
│       ├── app/              # Rutas: login, tablero, inventario, sitios, trabajos, auditoría…
│       ├── components/       # Componentes de UI (scope/: vistas de sitio, grupo y equipo)
│       ├── services/         # Cliente de la API
│       └── context/ hooks/ lib/ types/ constants/
├── docs/
│   ├── deployment/           # Guía de TLS
│   ├── runbooks/             # Rotación de claves y activación de RLS
│   ├── images/               # Capturas y diagramas de este README
│   └── tesis/                # PDF de la tesis
├── docker-compose.yml        # Stack de desarrollo: db, redis, backend, worker, beat
├── install.sh                # Instalador para servidor (producción)
└── .env.example              # Variables de docker compose
```

## Documentación de la tesis

- 📄 **[Tesis completa (PDF)](docs/tesis/Informe-PI-Martin-Endrek.pdf)**
- Runbooks de operación:
  - [Rotación de `FERNET_KEY`](docs/runbooks/fernet-key-rotation.md)
  - [Rotación de `JWT_SECRET_KEY`](docs/runbooks/jwt-secret-rotation.md)
  - [Activación de Row-Level Security](docs/runbooks/rls-activacion.md)
- [Configuración de TLS](docs/deployment/tls-setup.md)
- Referencia de la API: Swagger en `/docs` con la aplicación en marcha.

## Autores, agradecimientos y licencia

### Autores

- **Endrek, Marco**: mendrek@unc.edu.ar
- **Martin, Tomas**: tomas.martin@unc.edu.ar

### Agradecimientos

Quiero agradecer a la Universidad Nacional de Córdoba y a la Facultad de Ciencias
Exactas, Físicas y Naturales por la educación pública y de calidad que me permitió llegar
hasta aquí. A los docentes que me formaron y a mis directores, por su guía y disposición
durante el desarrollo de este proyecto. También a la Prosecretaría de Informática, y en
especial a mis compañeros de Redes, por abrirme las puertas y por convertir el trabajo
diario en un espacio de aprendizaje permanente. Gran parte de lo que se refleja en este
trabajo nació de esa experiencia.

A mis amigos de toda la vida y a los que me regaló esta etapa, por ser refugio en los
días difíciles y alegría en los buenos, y por recordarme siempre que no estaba solo.

A mi familia, por su apoyo incondicional, su amor y la confianza que depositaron
en mí desde el primer día. Sin ellos no lo hubiera logrado. Y a mi novio, por acompañarme
y alentarme en esta última etapa. A todos, gracias por celebrar cada avance como propio.
Este logro también es de ustedes.

Tomás.

Quiero expresar mi agradecimiento a la Universidad Nacional de Córdoba por la
formación que me brindó, y a los profesores que formaron parte de este camino, en especial
a Miguel Solinas, por su guía y dedicación durante el desarrollo de este proyecto
integrador. Agradezco también al equipo de Redes de la PSI, por todo lo que me enseñaron
y por hacer del trabajo un espacio en el que siempre fue un gusto estar y pertenecer.

A mi familia, por su apoyo constante y por haber sido un pilar fundamental a lo
largo de toda mi carrera, y en especial a mis padres, por brindarme la posibilidad de
dedicarme al estudio. Asimismo, a Agustina y a su familia, por su compañía y por
motivarme en todo momento a alcanzar mis metas.

A mis amigos, que estuvieron presentes, celebrando conmigo cada logro y
sosteniéndome en los momentos más difíciles. Y, de manera muy especial, a Fernando, la
estrella que me guía desde el comienzo de este camino. Este logro también es tuyo.

Marco.

### Licencia

Este proyecto se distribuye bajo la [PolyForm Noncommercial License 1.0.0](LICENSE):
se puede usar, modificar y compartir con fines no comerciales. El uso comercial no está
permitido por esta licencia.
