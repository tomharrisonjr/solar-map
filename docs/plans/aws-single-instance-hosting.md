# Host on AWS at solar-map.tomharrisonjr.com (single instance)

- GitHub Issue: #33
- Date: 2026-09-30
- Status: In Progress

## Steps

| Status | # | Step |
|--------|---|------|
| ✅ Done | 1 | Production-ready Django settings and server |
| ✅ Done | 2 | Production compose file and Caddy |
| ✅ Done | 3 | Replace the OpenStreetMap basemap |
| ✅ Done | 4 | Terraform: Lightsail instance, DNS and backups |
| ✅ Done | 5 | Terraform remote state in S3 |
| ⬜ Pending | 6 | First deploy, data load and docs |

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

Decisions (2026-10-04):

- **Lightsail**, not plain EC2: flat pricing, with the static IP, firewall and snapshots as a
  handful of resources and no VPC to manage.
- **All AWS resources are defined in Terraform** (step 4), not clicked through the console.
- **DNS is already in Route 53**, so Terraform looks up the existing hosted zone for
  `tomharrisonjr.com` and manages only the `solar-map` A record.
- **One Terraform workspace per environment** (`dev`, `staging`, `prod`), mirroring the work
  pattern. Resources are named `solar-map-<env>`, each env gets its own hostname
  (`solar-map-dev`, `solar-map-staging`, `solar-map-prod`), and the implicit `default`
  workspace is refused. An env can also have an **alias**: prod's real, public name is
  `solar-map.tomharrisonjr.com` (a CNAME to `solar-map-prod.tomharrisonjr.com`), and the
  env-specific name only 301-redirects to it. Envs without an alias just serve their own name. Only prod is expected to be applied for now; dev/staging cost the same
  ~$12/mo each, so create them only when needed.
- **Terraform state starts local and gitignored** (step 4), then moves to a private S3 bucket
  in step 5 (2026-10-05) because the stack is managed from several computers. Locking uses
  S3-native lock files (`use_lockfile`, Terraform >= 1.10), so no DynamoDB table.

Still open:

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

## Step 2 — Production compose file and Caddy (#36)

New `docker-compose.prod.yml` (override or standalone) and `Caddyfile`:

- `web`: gunicorn command, no source bind-mount, restart policy, `env_file` for prod secrets.
- `db`: same `imresamu/postgis:16-3.4` image, named volume, **no published port**, a real
  password from env rather than the dev default.
- `caddy`: `caddy:2` image publishing 80/443, reverse-proxying to `web:8000`, automatic Let's
  Encrypt certificate for `solar-map.tomharrisonjr.com`, persistent `/data` volume for certs.
- Health check on `web` so Caddy/compose can tell when it's up.

Verify locally by running the prod file with a `localhost` Caddy site (no real cert) and hitting
`/`, `/tiles/…`, `/api/facilities/nearest/`.

## Step 3 — Replace the OpenStreetMap basemap (#38)

`AGENTS.md` notes `tile.openstreetmap.org` is best-effort with no SLA and must be replaced
before deploying or heavy use. `facilities/static/facilities/map.js`, `map.html`, settings:

- Pick a provider with a free tier and a public-site-friendly policy (MapTiler, Stadia, or
  self-hosted PMTiles on S3/CloudFront). Decide in this step; note the choice and limits.
- Provider tile URL and API key come from settings/env (`.env.example`), passed to the page like
  `POLYGON_MIN_ZOOM` is; restrict the key by referrer/domain in the provider dashboard.
- Keep attribution always visible. Update the OSM-policy bullet in `AGENTS.md` and the README's
  "OSM 403" troubleshooting entry.

**Decision:** Stadia Maps, Alidade Smooth raster tiles. Free tier is 200k credits/month and
non-commercial only (fine for this personal project; revisit if that changes). Domain-based
auth means there is no key to leak: the deployed domain is registered in Stadia's dashboard and
`localhost` works unregistered, so `BASEMAP_API_KEY` is optional and only for other providers.
MapTiler's free tier (100k requests/month, hard stop when exceeded, logo required) was the
runner-up; self-hosted PMTiles was rejected as too much storage and ops for a small map. The
provider is swappable through `BASEMAP_*` env vars.
Note: `docker-compose.prod.yml` (step 2) passes an explicit list of variables to `web`, so
`BASEMAP_*` overrides need adding there if the Stadia default is ever changed in production.

## Step 4 — Terraform: Lightsail instance, DNS and backups (#42)

New `infra/` directory (Terraform, `required_version` and provider versions pinned; commit
`.terraform.lock.hcl`; gitignore `.terraform/`, `*.tfstate*`, `*.tfvars` but commit a
`terraform.tfvars.example`). Every resource the app needs on AWS is defined here:

- `aws_lightsail_instance`: 2 GB bundle, Ubuntu LTS blueprint, an SSH key pair, and a
  `user_data` script that installs Docker + Compose v2, enables unattended security upgrades,
  disables root and password SSH login, and clones the repo. It does **not** write secrets: the
  prod `backend/.env` is created by hand in step 6 so no secret lands in Terraform state.
- `aws_lightsail_static_ip` + `aws_lightsail_static_ip_attachment`: the address that survives
  instance rebuilds.
- `aws_lightsail_instance_public_ports`: 80 and 443 open to the world, 22 restricted to a
  `ssh_allowed_cidr` variable (your home IP).
- Daily snapshot (last 7 kept; Lightsail's `AutoSnapshot` add-on has no weekly option):
  an `add_on` block on `aws_lightsail_instance`. The DB itself is rebuildable, so this mainly saves `.env` and Caddy cert state.
- `data "aws_route53_zone"` for `tomharrisonjr.com` and an `aws_route53_record` A record
  `solar-map.tomharrisonjr.com` → the static IP.
- `outputs.tf`: static IP, the hostname, and a ready-to-paste `ssh` command.

Environments: `terraform.workspace` drives naming (`local.name`), an `Environment` default tag,
and a precondition that rejects any workspace outside `dev|staging|prod`. Per-environment values
live in committed `infra/envs/<env>.tfvars` (`subdomain`, which has no default so an env can't
silently reuse another's hostname, and an optional `alias`, the public name that CNAMEs to it).
`terraform output` prints `site_address` and `redirect_from`, the values for the server's `.env`; machine-specific values (`aws_profile`,
`ssh_allowed_cidr`) stay in the gitignored `infra/terraform.tfvars`, shared by every env. State
started in `infra/terraform.tfstate.d/<env>/` (gitignored) and moved to S3 in step 5.

Provider region is a variable (Lightsail is regional; default `us-east-1`). Credentials come from
the standard AWS profile/env, never from files in the repo.

Tasks: `task tf:init`, `tf:fmt`, and `tf:plan` / `tf:apply` taking `ENV=dev|staging|prod`
(validated by Task's `requires` enum) in `Taskfile.yml`; they create the workspace if missing and
select it with `TF_WORKSPACE`, so no selection lingers in local files; add `terraform fmt -check` and `terraform validate` to `task check`
(only when `terraform` is installed, so contributors without it aren't blocked) and add
Terraform to the `README.md` prerequisites table.

Verified locally: `caddy validate` accepts both identical and distinct names; a stub Caddy with
`app.localhost` / `app-prod.localhost` answers `301 https://app.localhost/<path>?<query>` for the
env-specific name and proxies (no redirect) for the public one; `docker compose config` resolves
`REDIRECT_FROM` to `SITE_ADDRESS` when unset.

Manual, non-Terraform follow-up: register `solar-map.tomharrisonjr.com` in the Stadia Maps
dashboard (the basemap authenticates by domain; unregistered hosts get the strict
unauthenticated rate limits).

Verify: `terraform validate`, then `terraform plan` reviewed before the first `apply` (which
creates billable resources, so the user runs or approves it); after apply confirm
`dig solar-map.tomharrisonjr.com` returns the static IP, SSH works, and `docker compose version`
runs on the box. A `terraform destroy` + `apply` drill proves it's reproducible.

**As shipped** (SSH access and the prod alias described here were later replaced; see
`docs/plans/ssm-access-and-env-hostnames.md`, #51):

- `infra/` as planned, plus workspaces (`dev`/`staging`/`prod`, `envs/<env>.tfvars`, the `default`
  workspace refused by a precondition) and an optional `alias`. Prod: A record
  `solar-map-prod.tomharrisonjr.com`, CNAME `solar-map.tomharrisonjr.com` → it. Region
  `us-east-2`, profile via `aws_profile`, bundle `small_3_0`.
- The public name is the alias: `Caddyfile` serves `SITE_ADDRESS, REDIRECT_FROM` and 301s any
  other host to `SITE_ADDRESS` (compose defaults `REDIRECT_FROM` to `SITE_ADDRESS`; documented in
  `backend/.env.example`). `terraform output` gives `site_address`/`redirect_from`.
- Snapshots are **daily** (last 7 kept): Lightsail's `AutoSnapshot` has no weekly option.
- Secrets stay a hand-made `backend/.env` (decision: Lightsail instances can't have IAM roles, so
  no native Parameter Store injection; EC2 + Parameter Store is the alternative if that matters).
- `task tf:*` wrappers (`ENV=` validated by Task's `requires` enum); `tf:check` is part of
  `task check`. README lists Terraform/AWS CLI as optional prerequisites; `AGENTS.md` layout updated.
- Verified: `task check` (ruff, 48 tests, `terraform fmt`/`validate`); `terraform plan` for dev
  and prod against the real account (6 and 7 resources to add, nothing else); `default` workspace
  and bad/missing `ENV` rejected; Caddy config validates and the redirect keeps path + query.
  **Not applied** — `terraform apply` (billable, ~$12/mo) is left for the user, and the live
  Let's Encrypt flow is untested until the instance exists.

## Step 5 — Terraform remote state in S3 (#49)

State is shared across the user's computers, so it lives in S3. Only dev has local state so far
(prod isn't applied), so the migration is small. Do this before the first prod `apply` in step 6.

- **Bootstrap root `infra/bootstrap/`** (its own `terraform` root, local state): the
  chicken-and-egg bucket can't live in the stack that uses it. It creates one S3 bucket named
  `solar-map-tfstate-<account-id>` (names are global; the account id keeps it unique) with
  versioning on, public access fully blocked, SSE (AES256) default encryption, a
  `prevent_destroy` lifecycle, a bucket policy denying non-TLS requests, and a lifecycle rule
  expiring noncurrent versions after ~90 days. Same region/profile variables as the main stack;
  output the bucket name. After creating the bucket, its own tiny state may be migrated into it
  under key `bootstrap/terraform.tfstate` (optional; document the choice).
- **Backend in `infra/versions.tf`:** `backend "s3" {}` with `key = "solar-map/terraform.tfstate"`,
  `use_lockfile = true`, `encrypt = true`; bucket/region/profile are partial config in a committed
  `infra/backend.hcl` (bucket and region aren't secret; profile stays out, supplied via
  `AWS_PROFILE` or `-backend-config`). Raise `required_version` to `>= 1.10` (S3 lock files).
  Non-default workspaces are stored by the backend at `env:/<workspace>/<key>`, so the
  per-env separation and the refused `default` workspace carry over unchanged.
- **Migrate:** `terraform init -backend-config=backend.hcl -migrate-state` for the existing
  `dev` workspace (answer yes to copying each workspace's state); confirm with `terraform plan`
  showing no changes, then delete the local `terraform.tfstate.d/` copies.
- **Taskfile:** `tf:bootstrap` (init + apply the bootstrap root; billable-free but creates AWS
  resources, so the user approves), `tf:init` passes `-backend-config=backend.hcl`, and
  `tf:check` uses `init -backend=false` as now. Update the `tf:plan/apply` comments about state
  location.
- **Docs:** README (new-computer setup: AWS credentials, `task tf:init`), `AGENTS.md` layout
  (`infra/bootstrap/`), and this plan's step 4 text about state location; add `infra/bootstrap`
  to `tf:check` and to `.gitignore` rules as needed (`.terraform/` is already ignored).

Verify: `task check`; `terraform -chdir=infra/bootstrap plan` reviewed before apply; after
migration `task tf:plan ENV=dev` shows no diff, the object exists in the bucket
(`aws s3 ls s3://<bucket>/env:/dev/`), and a second concurrent `plan` is rejected by the lock.

**As shipped:**

- `infra/bootstrap/` (local state, gitignored) creates `solar-map-tfstate-<account-id>` in
  `us-east-2`: versioned, AES256, public access blocked, TLS-only policy, `prevent_destroy`,
  noncurrent versions expire after 90 days. Applied once: 6 resources.
- The backend is `backend "s3"` in `infra/versions.tf` with `use_lockfile = true`;
  `infra/backend.hcl` (committed) holds bucket and region. `required_version` is `>= 1.10`.
  Credentials come from `AWS_PROFILE`, so the backend needs nothing extra beyond what the
  provider already uses. The bootstrap root's own state stays local (not worth a second bucket);
  it only needs to exist to apply changes to the bucket, and the bucket is recreatable.
- `dev` migrated: object `env:/dev/solar-map/terraform.tfstate`; a refresh against it finds every
  resource. (The plan's only diff was the firewall rule, from a changed home IP and IPv6
  defaults, unrelated to the backend.)
- `task tf:bootstrap`; `task tf:init` now passes `-backend-config=backend.hcl` and forwards
  extra args (`task tf:init -- -migrate-state`); `tf:check` also validates the bootstrap root.
- On another computer: install Terraform + AWS CLI, set `AWS_PROFILE`, `task tf:init`.

## Step 6 — First deploy, data load and docs

Done through the pipeline instead of by hand: `docs/plans/ci-cd-github-actions.md` (#53). Shell
access is SSM (`task ssm ENV=<env>`, no SSH, #51) and hostnames are `solar-map.tomharrisonjr.com`
for prod with `dev.solar-map.*` / `staging.solar-map.*` beneath it. The dev stack was deployed by
hand once to prove it; that sequence is now `scripts/deploy.sh`, run by the manual Deploy workflow:
first deploy creates `backend/.env`, starts the stack, migrates and loads the dataset.

- Prod's first deploy is step 5 of the CI/CD plan (after its Terraform and GitHub setup).
- Register `solar-map.tomharrisonjr.com` in the Stadia dashboard; its subdomains are covered.
- Verify over HTTPS: map renders, tiles load, `/api/facilities/nearest/?lat=...&lon=...` works,
  `/admin/` reachable, HTTP redirects to HTTPS (the workflow's smoke test covers the first three).
- `docs/deploy.md` is written (pipeline, deploy and rollback, first-time setup, rebuilds,
  dataset refresh); linked from `README.md`.
- Set this plan's `Status` to `Complete` once prod is live.

## Verification

`task check` for the code changes; then the live checks in step 6, plus a rebuild drill: destroy
the DB volume on the instance, `migrate` + `load_uspvdb`, confirm 6,611 facilities.

## Deferred to a later pass

- Uptime monitoring/alerting (e.g. Route 53 health check or a free external pinger).
- Moving to RDS PostGIS + ECS Express Mode if traffic or uptime needs grow.
- A CDN in front of `/tiles/` if tile load warrants it.
