# CLAUDE.md

Guidance for Claude Code working in this repository.

## Repo layout

A personal learning project: a single Django/GeoDjango backend backed by PostGIS,
loading the USPVDB solar-facility dataset and exposing it as a GeoJSON API. See
`docs/requirements.md` for the full design (goals, dataset choice, data model, risks).
There is no frontend yet — a Next.js map UI is a later phase, not part of this scaffold.

```
backend/
  Dockerfile           python:3.14-slim + gdal-bin/libgdal-dev/libgeos-dev/libproj-dev
  requirements.txt     Django, djangorestframework, djangorestframework-gis, psycopg
  requirements-dev.txt requirements.txt + ruff
  pyproject.toml       ruff config (E, F, I, UP, B, DJ; migrations excluded)
  manage.py
  .env.example          copy to backend/.env for local docker-compose runs (gitignored)
  config/               settings, urls, asgi/wsgi
  facilities/           the one app — models, serializers, views, urls, admin, tests.py
    management/commands/load_uspvdb.py   # ingestion command (stub — see TODO in file)
docs/
  requirements.md       design doc — read this for context before major changes
  plans/                plan docs for non-trivial features (see Workflow below)
```

Exclude `backend/**/migrations/*.py` from searches unless specifically investigating
schema history — they're generated.

## Commands

Everything runs through Docker Compose (GDAL/GEOS live in the `web` image, not on the
host — there's no host GDAL install to maintain):

```
docker compose up -d db                                   # start Postgres/PostGIS only
docker compose build web                                  # build the Django image
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py test          # tests
docker compose run --rm web python manage.py load_uspvdb <path-or-url>   # data ingestion
docker compose run --rm web ruff check .                   # lint
docker compose run --rm web ruff check --fix .              # lint, autofixing what's safe
docker compose up                                          # web (:8000) + db together
```

Ruff is configured in `backend/pyproject.toml` (pycodestyle, pyflakes, isort, pyupgrade,
bugbear, and Django-aware `DJ` rules; migrations excluded).

## Workflow

This repo has no GitHub remote configured yet, so there's no issue-tracking workflow to
follow — add one here once a remote exists.

- **Every non-trivial feature starts with a plan doc** before implementation: a markdown
  file under `docs/plans/` (e.g. `docs/plans/nearest-facility-api.md`) whose header is:
  ```markdown
  # <Title>

  - Date: YYYY-MM-DD
  - Status: Draft | In Progress | Complete
  ```
  followed by the plan content. Use Claude Code's plan mode to draft this, get it
  approved, then write it to the file before starting implementation. Update `Status` as
  work progresses.
- **Before considering a change done**, both of the following should pass:
  1. `docker compose run --rm web ruff check .`
  2. `docker compose run --rm web python manage.py test`

  Don't call something ready until you've actually run these yourself and confirmed they
  pass.
- Any documentation affected by a change (`README.md`, `docs/requirements.md`, or the
  feature's plan doc) is updated to reflect what shipped, and the plan doc's `Status` is
  set to `Complete`.


- Any new environment variables should be committed to .env.sample with documentation
## Conventions

- **GeoDjango data model**: `SolarFacility.geom` (the USPVDB panel-array polygon) is the
  source of truth; `centroid` is denormalized at ingestion time so nearest-facility
  queries run against points rather than polygons (cheaper, simpler), per
  `docs/requirements.md`. Populate `centroid` from `geom.centroid` on create/update —
  don't compute it ad hoc in queries.
- **API layer**: `djangorestframework-gis`'s `GeoFeatureModelSerializer` for GeoJSON
  output (see `facilities/serializers.py`); DRF `ModelViewSet`/`ReadOnlyModelViewSet` +
  router for endpoints (see `facilities/views.py` + `facilities/urls.py`).
- **Annotate class attributes.** New and touched classes should carry PEP 526 variable
  annotations on class-level attributes — model fields, `Meta`/config attributes, and
  viewset/serializer attributes (`queryset: QuerySet[SolarFacility] = ...`,
  `serializer_class: type[...] = ...`). Add `from __future__ import annotations` to any
  file that subscripts a Django field or model type this way, since Django's field
  classes aren't runtime-subscriptable. No mypy/django-stubs is configured, so this is
  for readability, not enforced — but keep it consistent with the existing `facilities`
  files.
- **PostGIS extension**: a fresh DB needs `CREATE EXTENSION postgis;` before the first
  migration. The `postgis/postgis` Docker image used by `docker-compose.yml` does this
  automatically for local dev. On AWS RDS (or any managed Postgres for prod), it must be
  run manually before the first `migrate` — see `docs/requirements.md` under Known Risks.
- **GDAL/GEOS friction**: if `manage.py migrate` or `LayerMapping` import fails with
  missing library errors, check that `backend/Dockerfile`'s apt packages
  (`gdal-bin`, `libgdal-dev`, `libgeos-dev`, `libproj-dev`) are present and the image was
  rebuilt (`docker compose build web`) — don't chase `GDAL_LIBRARY_PATH`/host installs,
  since Django always runs inside the container here.
