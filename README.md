# Erocraft Manager

> Server rental management platform whose only runtime dependency is Wings. Adds an end-user UI for console / files / billing / registration / renewal, plus an admin console for servers, users, hosts, certificates, alerting and billing.
>
> Language: **English** | [中文](README.zh-CN.md)

---

## 1. Overview

### 1.1 Components

This repository ships two independently deployable units:

| Unit | Path | Purpose |
|---|---|---|
| Manager | repo root | Backend API + scheduled jobs + Vue SPA. Runs on host A. |
| Agent | `agent/` | Per-node host metrics, probes, certificate deployment, Wings service control. Runs on every Wings node. |

The Manager backend is two processes:

- `manager-web`: FastAPI + Uvicorn, listens on `:5001`. REST API + console WebSocket.
- `manager-jobs`: APScheduler in its own process. Runs metrics pull, auto-suspend, auto-delete, certificate renewals, etc.

Both share the same `app/` codebase and database, and run independently of each other.

### 1.2 External Dependencies

**Hard runtime dependencies** :

| Dependency | Used for |
|---|---|
| Wings | Container lifecycle, power, console, files (per node; Manager calls `:8443` HTTPS and console WS directly) |
| MySQL / MariaDB | Sole datastore. Manager's own tables use the `manager_` prefix; the server / node records Wings needs live in the same database |
| nginx | Public reverse proxy; also serves the SPA static files |
| acme.sh | Certificate issuance / renewal, invoked by Manager via CLI |

**Relationship with Pterodactyl Panel**: Manager runs independently of the Panel process and interacts with the system only through the database and Wings. The database table / column names Manager uses, and the Laravel encryption format of Wings's `daemon_token`, are de-facto conventions of the Wings ecosystem. Pterodactyl Panel may be co-deployed and share the same database; in that case Panel's admin UI can be kept as a low-level fallback. When deploying Manager alone, you are responsible for initializing the schema and aligning keys with Wings.

### 1.3 Process Topology

```
            browser
              │
              ↓
         nginx :80/:443
              │
   ┌──────────┴───────────┐
   │                      │
   ↓                      ↓
SPA (static files)   manager-web :5001  ──direct R/W──→  MySQL
                          │
                          ├──HTTPS──→  Wings :8443    (per node)
                          │
                          └──HTTPS──→  Agent :48765   (per node)
                          ↑
                          │
                manager-jobs (APScheduler)  ─── periodic agent pull / automation
```

### 1.4 Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Pydantic v2, APScheduler, Alembic |
| Frontend | Vue 3.5, Vite 6, TypeScript, vue-i18n, ECharts, xterm.js, CodeMirror 6 |
| Database | MySQL / MariaDB |
| Agent | Python 3 + FastAPI + psutil + httpx |
| Certificates | acme.sh |

### 1.5 Repository Layout

```
app/                FastAPI backend
  api/routers/      HTTP routes
  services/         business logic (panel_db, wings, agent_client, cert_manager, billing, ...)
  jobs/             manager-jobs entrypoint and scheduler config
  schemas/          Pydantic models
  db/               ORM models + AsyncSession
  core/             config, security, time helpers
agent/              Node agent source
alembic/            Database migrations
frontend/           Vue 3 SPA
docs/               Architecture & design docs (ARCHITECTURE_V3 is authoritative)
templates/          Email template JSON
manager.sh          Backend service control script
.env.example        Environment template
```

---

## 2. Deployment

### 2.1 Prerequisites

- Linux x86_64 (verified on Debian 12 / Ubuntu 22.04+)
- At least one Wings node and a reachable MySQL / MariaDB instance (schema follows Wings ecosystem conventions; typically initialized by Pterodactyl Panel)
- Python 3.12+, Node.js 20+, nginx
- Network reach from host A to that MySQL (local or remote)
- acme.sh installed

### 2.2 Manager Backend

```bash
sudo mkdir -p /opt/erocraft_manager
sudo chown $USER:$USER /opt/erocraft_manager
git clone https://github.com/vvb7456/Erocraft_Manager.git /opt/erocraft_manager
cd /opt/erocraft_manager

python3.12 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

cp .env.example .env
$EDITOR .env
```

Required `.env` fields:

| Variable | Description |
|---|---|
| `SECRET_KEY` | ≥32 chars. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | Database connection |
| `PANEL_APP_KEY` | The Laravel `APP_KEY` used by the Wings ecosystem. Decrypts `nodes.daemon_token` and similar fields; if you share the database with Pterodactyl Panel, this must equal Panel's `.env` `APP_KEY`. |
| `CERT_ACME_SH_HOME` | acme.sh install directory |
| `CERT_ACME_SH_BIN` | acme.sh executable path |

Start:

```bash
bash manager.sh start          # starts web + jobs; runs `alembic upgrade head` first
bash manager.sh status
```

Artifacts: `erocraft_manager_web.pid`, `erocraft_manager_jobs.pid`. Logs in `logs/`.

### 2.3 Frontend

```bash
cd frontend
npm ci
npx vite build           # outputs to ../static/dist/
bash build-fonts.sh      # rebuild Material Symbols subset
```

### 2.4 nginx

Minimal config (add `listen 443 ssl;` + cert paths for HTTPS):

```nginx
server {
    listen 80;
    server_name panel.example.com;

    # Cert deployment endpoints can take >120s
    location /api/admin/certificates {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 400s;
    }

    # API + console WS
    location /api/ {
        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location / {
        root /opt/erocraft_manager/static/dist;
        try_files $uri /index.html;
    }
}
```

### 2.5 Per-Node Agent

Every Wings node needs an Agent. By convention it runs from `/opt/erocraft-agent` (note the dash; distinct from the in-repo `agent/`).

```bash
sudo mkdir -p /opt/erocraft-agent
cd /opt/erocraft-agent
python3 -m venv venv
venv/bin/pip install -r /path/to/erocraft_manager/agent/requirements.txt
sudo cp -r /path/to/erocraft_manager/agent ./agent

sudo cp agent/config.example.yaml ./agent.yaml
sudo $EDITOR ./agent.yaml
```

Key `agent.yaml` fields:

| Field | Meaning |
|---|---|
| `agent.role` | `wings_node` / `generic_host` / `synology_dsm` |
| `agent.bind` | Listen address; default `0.0.0.0:48765` |
| `agent.token` | Bearer token. High-entropy random string. Manager stores it encrypted. |
| `agent.allow_ips` | Optional source-IP allowlist |
| `wings.config_path` | Required when `role=wings_node`; points to wings config |

systemd:

```bash
sudo cp agent/erocraft-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now erocraft-agent
```

Register: in admin → Hosts → New, enter the agent endpoint URL (`http://<node>:48765`) and token. A probe runs automatically on save.

### 2.6 Agent Redeploy

The running agent does not auto-sync from the repo; push changes manually with the helper script:

```bash
bash scripts/deploy-agent.sh              # local
bash scripts/deploy-agent.sh <node-host>  # remote node
```

### 2.7 Database Migrations

`manager.sh start` runs migrations automatically. Manual:

```bash
venv/bin/alembic -c alembic.ini current
venv/bin/alembic -c alembic.ini history
venv/bin/alembic -c alembic.ini upgrade head
venv/bin/alembic -c alembic.ini revision --autogenerate -m "..."
```

All Manager-owned tables use the `manager_` prefix; migrations operate only on those tables.

---

## 3. Operations

### 3.1 Service Control

```bash
bash manager.sh start | stop | restart | status            # web + jobs
bash manager.sh start-web | stop-web | status-web
bash manager.sh start-jobs | stop-jobs | status-jobs
```

Startup runs `alembic upgrade head` first; if migration fails, check `logs/manager-web.log`.

### 3.2 Logs

| File / command | Contents |
|---|---|
| `logs/manager-web.log` | uvicorn access + application |
| `logs/manager-jobs.log` | scheduler jobs |
| `journalctl -u erocraft-agent` | node agent |
| `journalctl -u wings` | Wings |

Log level controlled by `LOG_LEVEL` in `.env` (`DEBUG / INFO / WARNING / ERROR`).

### 3.3 Scheduled Jobs

`manager-jobs` runs:

| Job | Trigger | Source |
|---|---|---|
| Metrics pull (all hosts) | every `MONITOR_INTERVAL_SEC` (default 60) | `.env` + runtime setting |
| Metrics pruning | daily | `MONITOR_RETENTION_DAYS` (default 30 days) |
| Auto-suspend / delete / reminder mail | daily at `AUTOMATION_RUN_HOUR:MINUTE` | runtime setting overrides |
| Certificate renewal & expiry alerts | daily | acme.sh + scanner |

`.env` is bootstrap fallback only. Runtime configuration lives in the database (admin → Settings).

### 3.4 Certificates

- **Source**: scan `CERT_ACME_SH_HOME` + acme.sh metadata
- **Renewal**: invokes `CERT_ACME_SH_BIN`
- **Targets**: local file / remote nginx (via Agent, with reload) / Synology DSM API
- **Webhook**: acme.sh `reloadcmd` or `deploy hook` calls `/api/public/cert-webhook`. Configure `CERT_WEBHOOK_TOKEN`.
- **Alert recipients**: `CERT_ALERT_EMAIL_ADMIN_IDS` or runtime setting

### 3.5 Hosts / Nodes

| Action | Path |
|---|---|
| Add a node | Admin → Hosts → New (endpoint + token) |
| Edit Wings config | Host detail → Wings tab; on save Manager writes the `nodes` table then pushes to wings `/api/update` |
| Restart Wings | Host detail → Wings → Restart (Agent triggers `systemctl restart wings`) |
| Allocations | Host detail → Allocations tab |
| Alert thresholds | Host detail → Settings tab (per-host overrides on top of global defaults) |

### 3.6 Backups

| Item | Command / path |
|---|---|
| Database | `mysqldump <DB_NAME> > db.sql` |
| Config | `.env`, `agent.yaml` (per node), nginx site files |
| Certificates | full `CERT_ACME_SH_HOME` |
| Container volumes | `/var/lib/pterodactyl/volumes` on each node |

### 3.7 Upgrade

```bash
cd /opt/erocraft_manager
git pull
venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npx vite build && cd ..
bash manager.sh restart                     # auto-migrates
bash scripts/deploy-agent.sh                # only when agent/ changed
```

### 3.8 Troubleshooting

| Symptom | Where to look |
|---|---|
| `manager.sh start` fails immediately | `logs/manager-web.log`; usually a missing `.env` field or migration failure |
| User console fails to connect | Verify nginx forwards `Upgrade/Connection` headers; verify wings `:8443` reachability from Manager |
| No monitoring data | Host detail → Settings → Probe; `systemctl status erocraft-agent`; verify token match |
| Certificate not renewed | grep `cert` in `logs/manager-jobs.log`; manually run `${CERT_ACME_SH_BIN} --renew -d <domain> --force` |
| Server creation fails | `lifecycle` entries in `logs/manager-web.log`; failures auto-rollback |
| Panel field decryption errors | confirm `PANEL_APP_KEY` matches the `APP_KEY` Wings was given when its `daemon_token` was generated (when sharing the database with Pterodactyl Panel, that means Panel's `.env` `APP_KEY`) |

### 3.9 One-liners

```bash
venv/bin/alembic -c alembic.ini current                      # current migration revision
tail -f logs/manager-jobs.log                                # tail jobs log
curl -fsS http://127.0.0.1:5001/api/version                  # health check
```

---

## License

See [LICENSE](LICENSE).
