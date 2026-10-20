<p align="right"><a href="README.md">Español</a> · <b>English</b></p>

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/AnsiAuth_Logo_Color_Tight.svg">
  <img src="frontend/public/brand/AnsiAuth_Logo_Color_Tight.svg" alt="AnsiAuth" width="480">
</picture>

<p><b>Multivendor Network Automation Platform</b></p>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Ansible](https://img.shields.io/badge/Ansible-13-EE0000?logo=ansible&logoColor=white)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-lightgrey)](LICENSE)

</div>

---

> **Academic context**
>
> | | |
> |---|---|
> | **Thesis title** | AnsiAuth |
> | **Authors** | Endrek, Marco · Martin, Tomas |
> | **Advisor** | Solinas, Miguel Angel |
> | **Co-advisor** | Bettucci, Marcos |
> | **Degree program** | Computer Engineering |
> | **School and university** | FCEFyN - UNC |
> | **Year** | 2026 |

## Table of contents

- [Summary](#summary)
- [Screenshots and demo](#screenshots-and-demo)
- [Main features](#main-features)
- [Technologies](#technologies)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Tests](#tests)
- [Project structure](#project-structure)
- [Thesis documentation](#thesis-documentation)
- [Authors, acknowledgements and license](#authors-acknowledgements-and-license)

## Summary

### Problem

Configuring network devices from different vendors (Cisco, Huawei) is usually done
one device at a time, over SSH, using each vendor's own command-line syntax. This
manual work is error-prone, requires every operator to know each vendor's CLI,
leaves no central record of who changed what, and does not allow delegating
permissions with different scopes (per site or per group of devices). A change that
fails halfway can leave a device in an intermediate state that nobody reverts.

### General objective

Develop a centralized management platform for administering multivendor switches
from a single interface, abstracting the syntax complexity of each vendor and reducing
manual intervention, while ensuring that operations on the network are idempotent,
traceable and reversible.

### Specific objectives

- Analyze network automation strategies and survey existing management tools, to
  ground the choice of the automation engine and the technology stack.
- Design a modular architecture that allows adding new resources without modifying
  the core logic of the changes.
- Abstract the syntax differences between vendors, so that adding a new one does not
  require modifying the rest of the system.
- Implement the operations on the main network resources: VLANs, physical ports,
  virtual interfaces (SVI) and the device's global configuration.
- Add asynchronous execution of changes, with retries on transient failures and
  rollback on permanent failures.
- Implement role-based access control (RBAC) and an audit log that makes it possible
  to reconstruct which change was applied, on which device, at what time and by which
  user [31].
- Organize devices into sites and groups, with scoped permissions and operations on
  sets of devices.
- Build a web interface to operate the system and check the state of the network
  without using each device's CLI.
- Validate the platform incrementally in a virtualized lab, a dedicated physical
  environment and production devices, evaluating its performance and adding
  mitigations for the failures detected.

## Screenshots and demo

<!-- IMAGE: login screen. PNG, ~1280 px wide -->
![Login](docs/images/captura-login.jpeg)

<!-- IMAGE: site dashboard with the device summary and the VLAN / PORTS / VIRTUAL-INTERFACES / GLOBAL-CONFIG tabs. PNG, ~1280 px wide -->
![Dashboard](docs/images/captura-panel.jpeg)

<!-- IMAGE: port editing on a device (several ports selected and the changes panel). PNG, ~1280 px wide -->
![Port editing](docs/images/captura-puertos.jpeg)

<!-- IMAGE: job list with statuses and the detail of one job (commands, rollback). PNG, ~1280 px wide -->
![Jobs](docs/images/captura-trabajos.jpeg)

## Main features

- **Authentication and sessions**: short-lived JWT access token and a rotating refresh token in an HttpOnly cookie, idle timeout and absolute session lifetime, re-authentication for destructive operations, lockout after failed attempts, request rate limiting and management of active sessions.
- **Multi-site organization**: Site → Group → Device hierarchy. `observer`, `operator` and `admin` permissions granted per site or per group, plus the system-wide `super-admin` role; the effective role is the highest of the applicable grants. Optional PostgreSQL Row-Level Security ([runbook](docs/runbooks/rls-activacion.md)).
- **Inventory**: registration of Cisco IOS / IOS-XE (`cisco_ios`) and Huawei VRP (`huawei_vrp`) devices with a password or a private key, both encrypted with Fernet; moving devices between groups and sites; the SSH host key is stored on the first connection and enforced afterwards.
- **VLANs**: create, rename and delete on one or several devices at once, and in batches.
- **Ports**: access or trunk mode, access VLAN, allowed VLANs, description, administrative state, PoE, storm-control and reset to defaults, editing several ports of one device in a single job.
- **Virtual interfaces (SVI)**: primary and secondary IPv4 addresses, IPv6, ACL, DHCP relay, description and state.
- **Global configuration**: hostname, NTP, DNS, log servers, SNMP, static routes and ACLs; running-config, version, logs and ARP/MAC tables, with a live MAC address search.
- **Asynchronous jobs**: every change runs as a job on a Celery worker, with per-device locking, pre-change state capture, retries on transient errors, rollback when the change fails, cancellation and live tracking from the UI.
- **Configuration saving** to the device's non-volatile memory.
- **Audit log**, insert-only, of every action, with filters and configurable retention.
- **`mock` mode** to develop and test without real devices.
- **Operations**: health check, JSON logs, optional Prometheus metrics and an installer for Linux servers ([`install.sh`](install.sh)).

## Technologies

| Area | Technology | Version |
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
| | Celery (worker and beat) | 5.x |
| | PyJWT · passlib · cryptography (Fernet) | 2.x · 1.7 · 46.0.7 |
| **Network automation** | Ansible · ansible-core | 13.5.0 · 2.20.4 |
| | ansible-runner | 2.4.3 |
| | `cisco.ios`, `ansible.netcommon`, `community.network` collections | latest from Ansible Galaxy |
| | Paramiko (`network_cli` transport) · OpenSSH (direct SSH with a key) | 2.x · system version |
| **Database and messaging** | PostgreSQL (psycopg 3) | 16 |
| | Redis (Celery broker and per-device locks) | 7 |
| **Infrastructure** | Docker and Docker Compose v2 | — |
| | Caddy (reverse proxy and TLS in production) | from the official repository |
| | Node.js (frontend in production) | 20 |
| **Quality** | pytest · httpx | 7.4.0 · 0.28.1 |
| | ESLint | 9 |

Exact versions live in [`backend/requirements.txt`](backend/requirements.txt) and [`frontend/package.json`](frontend/package.json). The value in parentheses is the resolved version when the file declares a range.

## Architecture

The system separates the web interface, the API and the execution of changes:

- **Frontend (Next.js)**: web interface consuming the `/api/v1` REST API. It keeps the access token in memory and renews the session with the refresh token from the cookie.
- **Backend (FastAPI)**: validates, authorizes according to the user's scope (site or group), writes the audit log and enqueues every change as a job: changes are never applied inside the HTTP request.
- **Worker (Celery)**: takes jobs from Redis. The orchestrator locks the device, captures its state, applies the change, retries on transient failures and rolls back on failure. It reaches the devices through `ansible-runner` (password authentication) or OpenSSH (key authentication).
- **Vendor drivers**: each vendor implements the same interface (`VendorDriver`), with its own commands and parsers. A plugin registry picks the driver from the device's `vendor` field, so adding a vendor does not change the orchestrator.
- **Celery Beat**: periodic tasks, such as recovering orphaned jobs.
- **PostgreSQL**: users, grants, sites, groups, devices (encrypted credentials), jobs, the state read from the devices and the audit log.
- **Redis**: Celery broker, per-device locks, global SSH session semaphore and per-device command rate.
- **Caddy** (production only): terminates TLS and serves `/api/*` and the UI from the same origin.

```mermaid
flowchart LR
    U["User<br/>(browser)"] -->|HTTPS| C["Caddy<br/>reverse proxy + TLS<br/>(production)"]
    C -->|"/"| F["Frontend<br/>Next.js"]
    C -->|"/api/*"| B["Backend API<br/>FastAPI"]
    F -.->|"REST /api/v1 + JWT"| B
    B --> P[("PostgreSQL 16")]
    B -->|enqueues jobs| R[("Redis 7")]
    BT["Celery Beat"] -->|periodic tasks| R
    R --> W["Celery worker<br/>orchestrator + drivers"]
    W --> P
    W -->|"ansible-runner<br/>(password)"| D["Switches<br/>Cisco IOS / IOS-XE<br/>Huawei VRP"]
    W -->|"OpenSSH<br/>(private key)"| D
```

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Git | any recent version | Clone the repository |
| Docker Engine + Docker Compose v2 plugin | Compose v2 (verified with 5.6.0) | Option A, and the `db` / `redis` services of option B |
| Node.js + npm | Node ≥ 20.9 (required by Next.js 16) | Frontend |
| Python | 3.12 (the Docker image's; also verified with 3.14) | Option B and the tests only |
| OpenSSH client and `sshpass` | system packages | Only in `real` mode outside Docker |

Ports used in development: `3000` (frontend), `8000` (API), `5432` (PostgreSQL) and `6379` (Redis), the last two bound to `127.0.0.1` only.

> **Note:** `docker-compose.yml` uses the `uid=` option on its `tmpfs` mounts, which Docker accepts and Podman rejects. Docker is recommended.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Marconia40/AnsiAuth-1.git ansiauth
cd ansiauth
```

### Option A: with Docker (recommended)

Starts PostgreSQL, Redis, the API, the worker and Celery Beat. Database migrations (`alembic upgrade head`) run automatically when the API container starts.

```bash
# 1. docker compose variables: copy the template and generate both keys
cp .env.example .env
sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')|" .env
sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')|" .env
# Edit .env and change BOOTSTRAP_ADMIN_PASSWORD (at least 12 characters)

# 2. Build and start the stack
docker compose up -d --build

# 3. Check that the API answers
curl http://localhost:8000/health
```

Then start the frontend:

```bash
cd frontend
cp .env.example .env.local    # NEXT_PUBLIC_API_URL=http://localhost:8000
npm ci
npm run dev                   # http://localhost:3000
```

Useful commands: `docker compose logs -f backend worker` (follow logs), `docker compose down` (stop, keep data) and `docker compose down -v` (stop and wipe the database).

### Option B: local backend (no Docker for the API)

PostgreSQL and Redis still run with Docker; the API and the worker run on the host, inside a virtual environment.

```bash
# 1. Database and Redis
docker compose up -d db redis

# 2. Virtual environment and dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# 3. Backend configuration
cp backend/.env.example backend/.env
sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')|" backend/.env
sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')|" backend/.env

# 4. Migrations and API
cd backend
alembic upgrade head
uvicorn app.main:app --reload            # http://localhost:8000
```

In another terminal, with the virtual environment activated, start the worker that runs the jobs:

```bash
cd backend
celery -A app.worker.celery_app worker --loglevel=info
```

The frontend starts the same way as in option A.

> **Important:** if options A and B share the same database, `FERNET_KEY` must be identical in `.env` and in `backend/.env`. Otherwise the worker cannot decrypt the credentials of the devices registered by the other backend (`InvalidToken`).

To work with real devices outside Docker (`EXECUTION_MODE=real`), also install the Ansible collections:

```bash
ansible-galaxy collection install cisco.ios ansible.netcommon community.network
```

### Initial data

There is no preloaded sample data. The migrations create the system site **Base Infrastructure** with its **Default** group. On first boot, the API creates the `admin` user (super-admin) with the password from `BOOTSTRAP_ADMIN_PASSWORD`.

### Server installation (production)

[`install.sh`](install.sh) installs Docker, Node.js and Caddy on Ubuntu 22.04/24.04 or RHEL/Fedora. It also clones the repository into `/opt/ansiauth`, generates random secrets, starts the stack with a production compose file and registers the systemd services. By default it serves the application over HTTPS on port `8443`.

```bash
sudo bash install.sh
```

The variables it accepts (`HTTPS_HOST`, `HTTPS_PORT`, `PUBLIC_URL`, `BRANCH`, `SKIP_UFW`, etc.) are documented at the top of the script. When it finishes, the initial credentials are stored in `/root/ansiauth-credentials.txt`. For TLS with your own certificate, see [`docs/deployment/tls-setup.md`](docs/deployment/tls-setup.md).

## Usage

1. Open **http://localhost:3000** and sign in as `admin` with the password from `BOOTSTRAP_ADMIN_PASSWORD`. There are no other test users: create them from the **Users** section.
2. In **Inventory**, register a device in the *Base Infrastructure* site, or first create your own site with **+ New site** on the organization dashboard. In `mock` mode (the default) any IP address works, because no connection is opened.
3. Navigate to the site, group or device and use the **VLAN**, **PORTS**, **VIRTUAL-INTERFACES** and **GLOBAL-CONFIG** tabs. Every change creates a job you can follow in **Jobs**, and it is recorded in **Audit**.

The API is documented with Swagger at **http://localhost:8000/docs**. Example with `curl`:

```bash
# Sign in and keep the access token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  --data-urlencode "username=admin" --data-urlencode "password=<BOOTSTRAP_ADMIN_PASSWORD>" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Register a device in site 1 (Base Infrastructure)
curl -s -X POST http://localhost:8000/api/v1/devices/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"sw-demo-01","host":"192.0.2.10","vendor":"cisco_ios","username":"admin","password":"demo-password","site_id":1}'

# Create VLAN 100 on that device: the answer holds one job_id per device
curl -s -X POST http://localhost:8000/api/v1/vlans/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"vlan_id":100,"name":"DEMO","devices":["sw-demo-01"]}'

# Check the job status
curl -s http://localhost:8000/api/v1/jobs/<job_id> -H "Authorization: Bearer $TOKEN"
```

To operate real devices, set `EXECUTION_MODE=real` in the corresponding `.env` and restart the API and the worker. Every variable is explained in [`.env.example`](.env.example) and [`backend/.env.example`](backend/.env.example).

## Tests

The backend suite (1427 tests, pytest) runs against a **dedicated** PostgreSQL database. As a safety measure, `conftest.py` refuses to use a database whose name does not contain `test`, because it wipes the schema when it starts. It needs a `backend/.env` with a valid `FERNET_KEY` (step 3 of option B).

```bash
# Test database (first time only)
docker compose up -d db
docker compose exec db createdb -U ansiauth ansiauth_test

# Run the suite in mock mode
cd backend
EXECUTION_MODE=mock python -m pytest
```

By default it connects to `postgresql+psycopg://ansiauth:ansiauth_dev_password@localhost:5432/ansiauth_test`. To use another test database, set `DATABASE_URL` before running `pytest`.

Frontend (type check and lint):

```bash
cd frontend
npx tsc --noEmit
npm run lint
```

## Project structure

```text
ansiauth/
├── backend/                  # REST API, worker and network automation
│   ├── app/
│   │   ├── api/              # FastAPI routers (/api/v1/...)
│   │   ├── core/             # Settings, JWT security, scope and roles, RLS, TLS
│   │   ├── db/               # SQLAlchemy session and ORM models, audit guard
│   │   ├── models/           # Domain models (device, port, SVI, job, audit…)
│   │   ├── repositories/     # Data access
│   │   ├── schemas/          # Pydantic request and response schemas
│   │   ├── services/         # Orchestrator, job queue, sync, audit
│   │   │   ├── parsers/      # CLI output parsing (VLAN, ports, SVI, global config, ARP/MAC)
│   │   │   └── vendors/      # Cisco IOS and Huawei VRP drivers, and the mock driver
│   │   ├── main.py           # API entry point
│   │   ├── worker.py         # Celery app and Beat schedule
│   │   └── tasks.py          # Celery tasks
│   ├── ansible/              # ansible.cfg and per-vendor playbooks
│   ├── migrations/           # Alembic migrations
│   ├── tests/                # pytest suite
│   ├── Dockerfile            # Image for the API, the worker and Beat
│   ├── requirements.txt
│   └── start.py              # uvicorn launcher with optional TLS
├── frontend/                 # Web interface (Next.js)
│   ├── public/brand/         # Logos
│   └── src/
│       ├── app/              # Routes: login, dashboard, inventory, sites, jobs, audit…
│       ├── components/       # UI components (scope/: site, group and device views)
│       ├── services/         # API client
│       └── context/ hooks/ lib/ types/ constants/
├── docs/
│   ├── deployment/           # TLS guide
│   ├── runbooks/             # Key rotation and RLS activation
│   ├── images/               # Screenshots and diagrams for this README
│   └── tesis/                # Thesis PDF
├── docker-compose.yml        # Development stack: db, redis, backend, worker, beat
├── install.sh                # Server installer (production)
└── .env.example              # docker compose variables
```

## Thesis documentation

- 📄 **[Full thesis (PDF, in Spanish)](docs/tesis/Informe-PI-Martin-Endrek.pdf)**
- Operations runbooks:
  - [`FERNET_KEY` rotation](docs/runbooks/fernet-key-rotation.md)
  - [`JWT_SECRET_KEY` rotation](docs/runbooks/jwt-secret-rotation.md)
  - [Row-Level Security activation](docs/runbooks/rls-activacion.md) (in Spanish)
- [TLS setup](docs/deployment/tls-setup.md)
- API reference: Swagger at `/docs` while the application is running.

## Authors, acknowledgements and license

### Authors

- **Endrek, Marco**: mendrek@unc.edu.ar
- **Martin, Tomas**: tomas.martin@unc.edu.ar

### Acknowledgements

I want to thank the Universidad Nacional de Córdoba and the Facultad de Ciencias
Exactas, Físicas y Naturales for the high-quality public education that brought me
this far. To the professors who trained me and to my advisors, for their guidance and
support throughout this project. Also to the Prosecretaría de Informática, and
especially to my colleagues on the Networks team, for opening their doors to me and for
turning everyday work into a place of constant learning. Much of what is reflected in
this work grew out of that experience.

To my lifelong friends and to the ones this stage of my life brought me, for being a
refuge on the hard days and a joy on the good ones, and for always reminding me that I
was not alone.

To my family, for their unconditional support, their love and the trust they placed in
me from day one. I could not have done it without them. And to my boyfriend, for being
by my side and encouraging me through this final stage. To all of you, thank you for
celebrating every step forward as your own. This achievement is yours too.

Tomás.

I want to express my gratitude to the Universidad Nacional de Córdoba for the education
it gave me, and to the professors who were part of this journey, especially Miguel
Solinas, for the guidance and dedication shown throughout this capstone project. I also
thank the PSI Networks team, for everything they taught me and for making work a place
where it was always a pleasure to be and to belong.

To my family, for their constant support and for being a fundamental pillar throughout
my whole degree, and especially to my parents, for giving me the chance to devote myself
to my studies. Likewise, to Agustina and her family, for their company and for always
motivating me to reach my goals.

To my friends, who were there celebrating every achievement with me and holding me up
in the hardest moments. And, very especially, to Fernando, the star that has guided me
since the beginning of this journey. This achievement is yours too.

Marco.

### License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE):
you may use, modify and share it for noncommercial purposes. Commercial use is not
permitted under this license.
