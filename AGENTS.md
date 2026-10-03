# AGENTS.md

Guidance for coding agents (Claude Code, Cursor, etc.) and humans working in this
repository. `CLAUDE.md` is a symlink to this file — edit `AGENTS.md`.

## Repo layout

A personal learning project: a single Django/GeoDjango backend backed by PostGIS,
loading the USPVDB solar-facility dataset and exposing it as a GeoJSON API. See
`docs/requirements.md` for the full design (goals, dataset choice, data model, risks).
The only UI is a minimal server-rendered MapLibre page at `/` (no build step); a Next.js
frontend is a later phase.

```
README.md              getting started for humans: prerequisites, `task setup`, troubleshooting
Taskfile.yml           dev workflow: setup/data:load/check/migrate, worktree new/rm/list (`task --list`)
.env.example            docker-compose port variables (DB_PORT, WEB_PORT); copy to .env (gitignored)
backend/
  Dockerfile           python:3.14-slim + gdal-bin/libgdal-dev/libgeos-dev/libproj-dev
  requirements.txt     Django, djangorestframework, djangorestframework-gis, psycopg
  requirements-dev.txt requirements.txt + ruff
  pyproject.toml       ruff config (E, F, I, UP, B, DJ; migrations excluded)
  manage.py
  .env.example          copy to backend/.env for local docker-compose runs (gitignored)
  config/               settings, urls, asgi/wsgi
  facilities/           the one app — models, serializers, views, urls, admin, tests.py
    tiles.py            # vector tiles built in PostGIS (ST_AsMVT), served at /tiles/{z}/{x}/{y}.mvt
    templates/facilities/map.html   # map page served at /
    static/facilities/map.js        # MapLibre map, fetches /api/facilities/ (+ /nearest/ on click)
    management/commands/load_uspvdb.py   # ingestion command (GeoJSON file/URL → upsert by case_id)
docs/
  requirements.md       design doc — read this for context before major changes
  plans/                plan docs for non-trivial features (see Workflow below)
```

Exclude `backend/**/migrations/*.py` from searches unless specifically investigating
schema history — they're generated.

## Commands

[Task](https://taskfile.dev) (`Taskfile.yml`) wraps the common workflows — run `task --list`:

```
task setup       # first time on a machine: backend/.env, build image, migrate, load data, venv + VS Code
task check       # lint + tests — the "before done" gate
task lint        # ruff
task test        # Django tests
task migrate     # start db, apply migrations
task data:load   # (re)load USPVDB from the official URL; `-- <path-or-url>` to override the source
task env         # create backend/.env from the example if missing (setup runs this)
task venv        # backend/.venv from requirements-dev.txt, for editor import resolution only (setup runs this)
task vscode      # add python.defaultInterpreterPath to gitignored .vscode/settings.json (setup runs this)
```

`load_uspvdb` with no argument downloads the official zip itself and finds the versioned
`.geojson` inside; a local file must live under `backend/` (the only host folder mounted
into the container). The dataset is never committed. `README.md` documents installing the
prerequisites (Docker, Task, Git) — keep it in sync when tooling changes.

Everything runs through Docker Compose (GDAL/GEOS live in the `web` image, not on the
host — there's no host GDAL install to maintain). The raw commands, for anything the
Taskfile doesn't cover:

```
docker compose up -d db                                   # start Postgres/PostGIS only
docker compose build web                                  # build the Django image
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py test          # tests
docker compose run --rm web python manage.py load_uspvdb [<path-or-url>] # data ingestion (default: official URL)
docker compose run --rm web ruff check .                   # lint
docker compose run --rm web ruff check --fix .              # lint, autofixing what's safe
docker compose up                                          # web (:8000) + db together
```

Ruff is configured in `backend/pyproject.toml` (pycodestyle, pyflakes, isort, pyupgrade,
bugbear, and Django-aware `DJ` rules; migrations excluded).

## Workflow

The repo is at `github.com/tomharrisonjr/solar-map`; `gh` is authenticated for issue/PR
work.

- **Every non-trivial feature starts with a plan doc** before implementation: a markdown
  file under `docs/plans/` (e.g. `docs/plans/nearest-facility-api.md`) whose header is:
  ```markdown
  # <Title>

  - GitHub Issue: #<n>
  - Date: YYYY-MM-DD
  - Status: Draft | In Progress | Complete

  ## Steps

  | Status | # | Step |
  |--------|---|------|
  | ⬜ Pending | 1 | <short step name> |
  | ⬜ Pending | 2 | <short step name> |
  ```
  Status column values: ✅ Done, 🔄 In Progress, ⬜ Pending, ⏸️ Deferred — no separate
  legend needed, the symbols are self-explanatory. The steps table is followed by a
  `## Context` section (why this change, what prompted it) and then one
  `## Step N — <name>` section per row with the concrete file-level detail, mirroring the
  table's step names and order.

  Use Claude Code's plan mode to draft this and get it approved. Once approved, **create
  a parent GitHub issue for the plan** (`gh issue create --title "<Title>" --body
  "<summary>"`) and put its number directly in the `GitHub Issue:` header — the plan doc
  is never written to disk with a placeholder. Update the table and overall `Status` as
  work progresses.
- **Starting a step doesn't happen until implementation begins** — steps don't get their
  own issue or branch just for being planned. When you're ready to work on one (e.g. "start
  step 3 of `docs/plans/foo.md`"), use `/start-work <plan-doc> <step-number>`, which:
  1. Creates a child GitHub issue for that step, linked to the plan's parent issue.
  2. Creates an isolated git worktree with `task wt:new -- <type>/gh-<issue>-<desc>` —
     `type` is `chore`/`bug`/`feature`, `issue` is the new child issue number, `desc` is a
     slugified step title. Working in a worktree means this can be kicked off regardless
     of what branch or process is currently active in the main checkout.
  See `.claude/commands/start-work.md` for the exact procedure.
- **Before considering a change done**, `task check` must pass (it runs
  `docker compose run --rm web ruff check .` and
  `docker compose run --rm web python manage.py test`).

  Don't call something ready until you've actually run these yourself and confirmed they
  pass.
- Any documentation affected by a change (`README.md`, `docs/requirements.md`, or the
  feature's plan doc) is updated to reflect what shipped, and the plan doc's `Status` is
  set to `Complete`.
- Any new environment variables are committed to the relevant `.env.example`
  (`backend/.env.example` for Django settings, the root `.env.example` for docker-compose
  variables) with documentation.
- PRs use `.github/PULL_REQUEST_TEMPLATE/template.md`; link the issue with `Closes #<n>`.

## Worktrees

Each in-flight branch gets its own git worktree, so the primary checkout stays free
(e.g. to start another branch while a build or review is running). Use the Taskfile
rather than raw `git worktree` so setup is consistent:

- `task wt:new -- <type>/gh-<n>-<desc>` — creates the branch from local `main`
  (override with `BASE=<ref>`) in a sibling folder, `../solar-map.worktrees/<branch-slug>/`;
  symlinks `backend/.env` from the primary checkout (one source of truth for local
  config); writes a worktree-local `.env` with free `DB_PORT`/`WEB_PORT` so its compose
  stack can run beside the primary checkout's. Then work from that folder.
- `task wt:rm -- <branch>` — after the PR merges: stops the worktree's compose stack and
  deletes its DB volume, removes the worktree, and deletes the (merged) branch.
- `task wt:list` — show worktrees.
- Dependencies, build caches and other gitignored state aren't shared between worktrees;
  Docker containers/volumes are per-worktree (named after the folder).
- **Claude Code:** `/start-work` switches the session into the new worktree with the
  `EnterWorktree` tool (`path` parameter). `.claude/settings.json` allows that tool without a
  prompt. `ExitWorktree` is deliberately *not* allowed: with `action: "remove"` it deletes a
  worktree and its branch, so it keeps asking.

## Conventions

- **GeoDjango data model**: `SolarFacility.geom` (the USPVDB panel-array polygon) is the
  source of truth; `centroid` is denormalized at ingestion time so nearest-facility
  queries run against points rather than polygons (cheaper, simpler), per
  `docs/requirements.md`. Populate `centroid` from `geom.centroid` on create/update —
  don't compute it ad hoc in queries.
- **API layer**: `djangorestframework-gis`'s `GeoFeatureModelSerializer` for GeoJSON
  output (see `facilities/serializers.py`); DRF `ModelViewSet`/`ReadOnlyModelViewSet` +
  router for endpoints (see `facilities/views.py` + `facilities/urls.py`).
- **Vector tiles (`facilities/tiles.py`)**: the map reads facilities from
  `/tiles/{z}/{x}/{y}.mvt`, never from the list API (the full polygon set is ~25 MB). The tile
  SQL is static text with `z/x/y` and the constants bound as parameters — never build it with
  string formatting. Keep the bbox filter index-friendly: transform the *tile envelope* to 4326
  and use `column && envelope` (GiST index on `geom`/`centroid`), don't transform the column.
  Layers are disjoint by zoom (`points` below `POLYGON_MIN_ZOOM`, `polygons` from it), and the
  page gets `POLYGON_MIN_ZOOM` from the server so client layers and tiles can't drift apart.
  Send only what the client draws; measure with real data before tuning (numbers in
  `docs/plans/vector-tile-map.md`).
- **Basemap tiles**: raster tiles from Stadia Maps' Alidade Smooth (free tier: 200k
  credits/month, non-commercial only), configured by `BASEMAP_*` settings/env
  (`BASEMAP_TILES_URL`, `BASEMAP_ATTRIBUTION`, `BASEMAP_MAX_ZOOM`, optional `BASEMAP_API_KEY`)
  and handed to the page as JSON (`json_script`) by `basemap_config()` in
  `facilities/views.py` — never hardcode a tile host in `map.js`. Stadia authenticates by the
  request's `Origin`/`Referer` (register new domains in its dashboard; `localhost` works
  unregistered), so keep `SECURE_REFERRER_POLICY` non-restrictive. Keep attribution always
  visible (`attributionControl: { compact: false }`). Don't use `tile.openstreetmap.org`: it's
  best-effort with no SLA and blocks heavy or referrer-less use.
- **Annotate class attributes.** New and touched classes should carry PEP 526 variable
  annotations on class-level attributes — model fields, `Meta`/config attributes, and
  viewset/serializer attributes (`queryset: QuerySet[SolarFacility] = ...`,
  `serializer_class: type[...] = ...`). Add `from __future__ import annotations` to any
  file that subscripts a Django field or model type this way, since Django's field
  classes aren't runtime-subscriptable. No mypy/django-stubs is configured, so this is
  for readability, not enforced — but keep it consistent with the existing `facilities`
  files.
- **PostGIS extension**: a fresh DB needs `CREATE EXTENSION postgis;` before the first
  migration. The `imresamu/postgis` Docker image used by `docker-compose.yml`
  (multi-arch, so it runs natively on Apple Silicon) does this automatically for local dev. On AWS RDS (or any managed Postgres for prod), it must be
  run manually before the first `migrate` — see `docs/requirements.md` under Known Risks.
- **GDAL/GEOS friction**: if `manage.py migrate` or `LayerMapping` import fails with
  missing library errors, check that `backend/Dockerfile`'s apt packages
  (`gdal-bin`, `libgdal-dev`, `libgeos-dev`, `libproj-dev`) are present and the image was
  rebuilt (`docker compose build web`) — don't chase `GDAL_LIBRARY_PATH`/host installs,
  since Django always runs inside the container here.
