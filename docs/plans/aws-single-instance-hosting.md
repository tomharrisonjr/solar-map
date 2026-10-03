# Host on AWS at solar-map.tomharrisonjr.com (single instance)

- GitHub Issue: #33
- Date: 2026-09-30
- Status: In Progress

## Steps

| Status | # | Step |
|--------|---|------|
| ✅ Done | 1 | Production-ready Django settings and server |
| ⬜ Pending | 2 | Production compose file and Caddy |
| ⬜ Pending | 3 | Replace the OpenStreetMap basemap |
| ⬜ Pending | 4 | Provision the instance, DNS and backups |
| ⬜ Pending | 5 | First deploy, data load and docs |

## Context

Goal: serve the app publicly at `solar-map.tomharrisonjr.com` from a personal AWS account.
The work-style setup (ECS cluster, ALB + target groups, VPC with public/private subnets, RDS,
Terraform) is far more than a read-only personal map needs.

Options considered:

| Option | Rough cost | Verdict |
|---|---|---|
| **Lightsail instance (or small EC2) running Docker Compose** | ~$10–12/mo | **Chosen** |
| ECS Express Mode (Fargate + ALB from one command) | ~$20+/mo, ALB dominates | Good app story, but still needs RDS PostGIS + a VPC |
| App Runner | low | Needs RDS via VPC connector; believed closed to new customers in 2026 — verify before considering |
| Full ECS + RDS + Terraform | $50+/mo | Overkill |

Why a single instance works here: the database is a **disposable cache** — `load_uspvdb`
rebuilds all ~6.6k rows from the public USPVDB zip in seconds — so managed-DB durability
(multi-AZ, PITR, failover) buys nothing. The same `imresamu/postgis` container used in dev can
run in prod. Trade-off accepted: we patch the OS and monitor the box ourselves, and deploys have
a few seconds of downtime.

Escape hatch: the container image and env-var config from steps 1–2 carry over unchanged if we
later move to RDS PostGIS + ECS Express Mode.

Open questions to settle while implementing:

- Lightsail vs plain EC2 (Lightsail: flat pricing, built-in static IP + snapshots; EC2: more
  familiar, Terraform-friendly). Default: Lightsail.
- Where DNS for `tomharrisonjr.com` lives (Route 53 or the registrar) — only an A record is needed.
- Deploy mechanism: `git pull` + `docker compose up -d --build` over SSH (default), vs. pushing
  images to ECR.

## Step 1 — Production-ready Django settings and server (#34)

`backend/config/settings.py`, `backend/requirements.txt`, `backend/.env.example`:

- Run under `gunicorn` (add to `requirements.txt`) instead of `runserver`.
- Serve static files with WhiteNoise (middleware + `STATIC_ROOT`; `collectstatic` at image build
  or container start). Keep the existing middleware ordering comment intact.
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` are already env-driven; add `CSRF_TRUSTED_ORIGINS`
  (comma-separated), and behind-proxy settings (`SECURE_PROXY_SSL_HEADER`, `CSRF_COOKIE_SECURE`,
  `SESSION_COOKIE_SECURE`) gated on an env flag so local dev is unaffected. Keep
  `SECURE_REFERRER_POLICY` non-restrictive (OSM/tile-provider requirement in `AGENTS.md`).
- Refuse to start in prod with the default `SECRET_KEY`.
- Document every new variable in `backend/.env.example`.

Tests: settings parse the new variables (list splitting, defaults); static files served with
`DEBUG=False`.

## Step 2 — Production compose file and Caddy

New `docker-compose.prod.yml` (override or standalone) and `Caddyfile`:

- `web`: gunicorn command, no source bind-mount, restart policy, `env_file` for prod secrets.
- `db`: same `imresamu/postgis:16-3.4` image, named volume, **no published port**, a real
  password from env rather than the dev default.
- `caddy`: `caddy:2` image publishing 80/443, reverse-proxying to `web:8000`, automatic Let's
  Encrypt certificate for `solar-map.tomharrisonjr.com`, persistent `/data` volume for certs.
- Health check on `web` so Caddy/compose can tell when it's up.

Verify locally by running the prod file with a `localhost` Caddy site (no real cert) and hitting
`/`, `/tiles/…`, `/api/facilities/nearest/`.

## Step 3 — Replace the OpenStreetMap basemap

`AGENTS.md` notes `tile.openstreetmap.org` is best-effort with no SLA and must be replaced
before deploying or heavy use. `facilities/static/facilities/map.js`, `map.html`, settings:

- Pick a provider with a free tier and a public-site-friendly policy (MapTiler, Stadia, or
  self-hosted PMTiles on S3/CloudFront). Decide in this step; note the choice and limits.
- Provider tile URL and API key come from settings/env (`.env.example`), passed to the page like
  `POLYGON_MIN_ZOOM` is; restrict the key by referrer/domain in the provider dashboard.
- Keep attribution always visible. Update the OSM-policy bullet in `AGENTS.md` and the README's
  "OSM 403" troubleshooting entry.

## Step 4 — Provision the instance, DNS and backups

Mostly console/CLI work; record the exact commands in `docs/deploy.md`:

- Lightsail instance (2 GB RAM, Ubuntu LTS) with Docker + Compose v2; static IP attached;
  firewall open on 22 (restricted to home IP), 80, 443 only.
- DNS: A record `solar-map.tomharrisonjr.com` → static IP.
- Weekly automatic snapshot. The DB itself is rebuildable, so the snapshot mainly saves the
  `.env` and Caddy cert state.
- Optional: capture the above as ~30 lines of Terraform if reproducibility becomes worthwhile.
- Basic hygiene: unattended security upgrades, SSH key only, no root login.

## Step 5 — First deploy, data load and docs

- Clone the repo on the instance, create prod `backend/.env`, `docker compose -f … up -d
  --build`, `migrate`, `load_uspvdb` (the default source downloads the official zip).
- Verify over HTTPS: map renders, tiles load, `/api/facilities/nearest/?lat=…&lon=…` works,
  `/admin/` reachable, HTTP redirects to HTTPS.
- Write `docs/deploy.md` (provisioning, deploy/update routine, refreshing data, restoring from
  snapshot); link it from `README.md`; update `docs/requirements.md` and `AGENTS.md` layout.
- Set this plan's `Status` to `Complete`.

## Verification

`task check` for the code changes; then the live checks in step 5, plus a rebuild drill: destroy
the DB volume on the instance, `migrate` + `load_uspvdb`, confirm 6,611 facilities.

## Deferred to a later pass

- CI-driven deploys (GitHub Actions over SSH or via ECR).
- Uptime monitoring/alerting (e.g. Route 53 health check or a free external pinger).
- Moving to RDS PostGIS + ECS Express Mode if traffic or uptime needs grow.
- A CDN in front of `/tiles/` if tile load warrants it.
