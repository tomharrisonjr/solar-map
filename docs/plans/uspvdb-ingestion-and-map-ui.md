# Data ingestion, nearest-facility API, and a minimal map UI

- GitHub Issue: #2
- Date: 2026-09-28
- Status: Draft

## Steps

| Status | # | Step |
|--------|---|------|
| ⬜ Pending | 1 | Ingestion: add `case_id` field + implement `load_uspvdb` |
| ⬜ Pending | 2 | Nearest-facility API endpoint |
| ⬜ Pending | 3 | Minimal map UI (server-rendered, no Next.js yet) |
| ⬜ Pending | 4 | Wrap-up (lint, tests, docs) |

## Context

The backend scaffold exists (models, DRF viewset/serializer, routing) but two things
block any visible progress: `load_uspvdb` is a stub that raises `NotImplementedError`,
and there's no nearest-facility query or any UI at all. The user wants to see a working
web UI sooner rather than later, rather than fully building out the backend first. The
fastest path to that is a lean vertical slice: get real data in the DB, add the one query
endpoint a map needs, then serve a minimal server-rendered map page — deferring Next.js,
per `docs/requirements.md`'s note that a minimal server-rendered template is an
acceptable starting point.

Researched the actual USPVDB schema (it's not in this repo) via the USGS site:

- Polygon geometry ships in `uspvdbGeoJSON.zip` (download page:
  <https://eerscmap.usgs.gov/uspvdb/data/>) — the plain API endpoint only returns points,
  so ingestion must consume the downloaded GeoJSON file, not the API.
- Feature properties include `case_id` (stable unique integer, always present),
  `eia_id` (nullable — not every facility links to an EIA plant), `p_name`, `p_state`,
  `p_cap_ac`, `p_year`.
- `case_id` isn't currently a model field. `eia_id` is nullable+unique, so it can't be
  the idempotency key for upserts. Adding `case_id` as the true unique key is a small,
  necessary model change.

## Step 1 — Ingestion: add `case_id`, implement `load_uspvdb`

- `backend/facilities/models.py`: add
  `case_id: models.IntegerField[int] = models.IntegerField(unique=True)` to
  `SolarFacility` (the stable USPVDB identifier). Keep `eia_id` as-is (nullable).
- Generate the migration (`makemigrations`).
- `backend/facilities/management/commands/load_uspvdb.py`: replace the stub.
  - Accept the `source` arg as either a local file path or an `http(s)://` URL to a
    USPVDB GeoJSON file (document in the docstring/help text that the user downloads
    `uspvdbGeoJSON.zip` from the USGS site and extracts it first — no zip handling in
    scope).
  - Parse with `json.load` (local) or `urllib.request` (URL).
  - For each feature: build geometry via `GEOSGeometry(json.dumps(feature["geometry"]))`,
    wrap `Polygon` in `MultiPolygon` if needed (field is `MultiPolygonField`), compute
    `centroid = geom.centroid`.
  - `SolarFacility.objects.update_or_create(case_id=..., defaults={...})` per feature,
    wrapped in `transaction.atomic()`, with progress output every ~500 records via
    `self.stdout.write`.
  - Map: `p_name`→`name`, `p_state`→`state`, `p_cap_ac`→`capacity_mw`, `p_year`→
    `install_year`, `eia_id`→`eia_id` (nullable, cast if present).
- Verify: `docker compose run --rm web python manage.py migrate`, then run the ingestion
  command against a downloaded extract and confirm row count via
  `docker compose run --rm web python manage.py shell -c "from facilities.models import SolarFacility; print(SolarFacility.objects.count())"`.

## Step 2 — Nearest-facility API endpoint

- `backend/facilities/views.py`: add a `@action(detail=False)` method `nearest` on
  `SolarFacilityViewSet` — `GET /api/facilities/nearest/?lat=..&lon=..&n=5` — using the
  `Distance` annotation pattern already sketched in `docs/requirements.md`:
  `SolarFacility.objects.annotate(distance=Distance("centroid", pt)).order_by("distance")[:n]`.
  Validate `lat`/`lon` are present and parseable; default `n=5`, cap it (e.g. 25) to
  avoid unbounded queries.
- Reuse `SolarFacilitySerializer` for the response (still GeoJSON `FeatureCollection`).
- Also set `pagination_class = None` on the main list route (or override `list`) so
  `/api/facilities/` returns a full `FeatureCollection` for the map to render — the
  dataset is small (~thousands of rows) per `docs/requirements.md`, so this is simpler
  than teaching the frontend to page through `GeoJsonPagination`.
- Add tests in `facilities/tests.py` covering: nearest ordering with a few seeded
  facilities, and missing/invalid `lat`/`lon` returning 400.

## Step 3 — Minimal map UI (server-rendered, no Next.js yet)

- New `facilities/templates/facilities/map.html` + a plain Django view (not DRF) wired
  in `config/urls.py` at `/` (or `/map/`), rendering a single page that loads MapLibre
  GL JS from a CDN (`<script>`/`<link>` tags — no build step, no new dependency).
- Inline (or a small static JS file under `facilities/static/facilities/map.js`) that:
  - Fetches `/api/facilities/`, renders panel-array polygons as a MapLibre GeoJSON
    source/layer (centered on the continental US).
  - On map click, calls `/api/facilities/nearest/?lat=..&lon=..&n=5`, highlights the
    returned facilities, and lists name/state/capacity/distance in a sidebar panel.
- No new Python/JS package dependencies — MapLibre via CDN keeps this out of
  `requirements.txt` and avoids standing up a Next.js toolchain for what's still a
  learning-project checkpoint.
- Verify manually: `docker compose up`, load `http://localhost:8000/`, click the map,
  confirm nearest facilities highlight and list correctly.

## Step 4 — Wrap-up per repo workflow

- `docker compose run --rm web ruff check .` and
  `docker compose run --rm web python manage.py test` must both pass.
- Update `docs/requirements.md`: mark ingestion/nearest-query/basic-map-UI core features
  as done where applicable; note the `case_id` field addition under the data model
  section.
- Set this plan doc's `Status` to `Complete` once shipped, and fill in the GitHub Issue
  reference once one exists.
- New env vars: none anticipated (CDN-loaded JS needs no API keys); if a basemap tile
  source requiring a key gets added later, document it in `backend/.env.example` then.

## Deferred to a later pass (not in this slice)

- Next.js frontend (requirements.md leaves this as a later phase).
- Spatial join against forest-loss/protected-area data (stretch goal).
- Raw-SQL KNN (`<->`) performance comparison (open question in requirements.md).
