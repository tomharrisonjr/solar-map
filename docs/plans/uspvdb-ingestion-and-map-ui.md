# Data ingestion, nearest-facility API, and a minimal map UI

- GitHub Issue: #2
- Date: 2026-09-28
- Status: Complete

## Steps

| Status | # | Step |
|--------|---|------|
| ✅ Done | 1 | Ingestion: add `case_id` field + implement `load_uspvdb` |
| ✅ Done | 2 | Nearest-facility API endpoint |
| ✅ Done | 3 | Minimal map UI (server-rendered, no Next.js yet) |
| ✅ Done | 4 | Wrap-up (lint, tests, docs) |

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

## Step 1 — Ingestion: add `case_id`, implement `load_uspvdb` (#3)

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

## Step 2 — Nearest-facility API endpoint (#5)

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
  **Superseded:** the "small dataset" assumption was wrong for polygons — the real data is
  6,611 facilities but ~25 MB as GeoJSON. The list is paginated again and the map uses vector
  tiles; see `docs/plans/vector-tile-map.md`.
- Add tests in `facilities/tests.py` covering: nearest ordering with a few seeded
  facilities, and missing/invalid `lat`/`lon` returning 400.

## Step 3 — Minimal map UI (server-rendered, no Next.js yet) (#10)

- New `facilities/templates/facilities/map.html` + a plain Django view (not DRF) wired
  in `config/urls.py` at `/` (or `/map/`), rendering a single page that loads MapLibre
  GL JS from a CDN (`<script>`/`<link>` tags — no build step, no new dependency).
- Inline (or a small static JS file under `facilities/static/facilities/map.js`) that:
  - Fetches `/api/facilities/`, renders panel-array polygons as a MapLibre GeoJSON
    source/layer (centered on the continental US). *(Superseded: the map now loads vector
    tiles from `/tiles/{z}/{x}/{y}.mvt` — see `docs/plans/vector-tile-map.md`.)*
  - On map click, calls `/api/facilities/nearest/?lat=..&lon=..&n=5`, highlights the
    returned facilities, and lists name/state/capacity/distance in a sidebar panel.
- No new Python/JS package dependencies — MapLibre via CDN keeps this out of
  `requirements.txt` and avoids standing up a Next.js toolchain for what's still a
  learning-project checkpoint.
- Verify manually: `docker compose up`, load `http://localhost:8000/`, click the map,
  confirm nearest facilities highlight and list correctly.

**As shipped:**

- `MapView` (a `TemplateView`) in `facilities/views.py`, wired at `/` in `config/urls.py`;
  `map.html` loads MapLibre GL JS 5.6.0 from unpkg (pinned), with an OpenStreetMap raster
  basemap (no API key). `map.js` is a static file; result names are rendered with
  `textContent`, not `innerHTML`, since they come from external data.
- Nearest markers use the API's denormalized `centroid` property so results stay visible
  at country zoom, where panel-array polygons are only specks.
- **OSM tile usage policy** (<https://operations.osmfoundation.org/policies/tiles/>): the
  first version was blocked with `403 Access Blocked` because Django's default
  `Referrer-Policy: same-origin` stripped the `Referer` from tile requests, which the policy
  requires browsers to send. Fixed with `SECURE_REFERRER_POLICY =
  "strict-origin-when-cross-origin"` (regression test added), and attribution is forced
  expanded (`attributionControl: { compact: false }`) since it may not sit behind a toggle.
  The public OSM server is best-effort with no SLA; use a tile provider before deploying.
- **Deviation — Django pin bumped** from `>=5.1,<5.2` to `>=5.2.8,<5.3`. The image runs
  Python 3.14, which Django 5.1 doesn't support: the test client's template-context copy
  raised `AttributeError: 'super' object has no attribute 'dicts'`, and the same `Context`
  copy is used by `{% include %}` (so e.g. the admin). 5.2.8 is the first 5.2 release
  supporting 3.14. DRF 3.15 / DRF-GIS 1.1 work unchanged; image rebuilt.
- Verified: `task check` (9 tests, incl. page, static-file and Referrer-Policy tests) and
  migration drift check pass. The real server was loaded with 6 synthetic facilities via
  `load_uspvdb` and `/`, `/static/facilities/map.js`, `/api/facilities/` and `/nearest/`
  were fetched over HTTP; `map.js` was also run under Node with stubbed MapLibre/DOM
  against the live API (load + click → correct sidebar, markers, bounds). The page was then
  checked in a browser by the author: tiles load once the Referrer-Policy fix was in.

## Step 4 — Wrap-up per repo workflow (#12)

- `docker compose run --rm web ruff check .` and
  `docker compose run --rm web python manage.py test` must both pass.
- Update `docs/requirements.md`: mark ingestion/nearest-query/basic-map-UI core features
  as done where applicable; note the `case_id` field addition under the data model
  section.
- Set this plan doc's `Status` to `Complete` once shipped, and fill in the GitHub Issue
  reference once one exists.
- New env vars: none anticipated (CDN-loaded JS needs no API keys); if a basemap tile
  source requiring a key gets added later, document it in `backend/.env.example` then.

**As shipped:**

- `task check` passes on `main` from a fresh worktree (ruff clean, 9 tests OK); a fresh
  database migrates cleanly through `0001_initial` and `0002_solarfacility_case_id`, and
  `makemigrations --check` reports no drift.
- `docs/requirements.md`: the four core features are marked done with what shipped; the
  data-model sketch now includes `case_id` and why; the stack, repo layout and risks
  sections match reality (Django 5.2 / Python 3.14, Taskfile and `AGENTS.md`, the OSM tile
  usage policy).
- New env vars: none. (`DB_PORT`/`WEB_PORT` for docker-compose were documented earlier in
  the root `.env.example` as part of the worktree workflow; the OSM Referrer-Policy fix is a
  Django setting, not an env var.)
- Status set to `Complete`.

**Open follow-ups (not blocking, deliberately not done here):**

- ~~Run `load_uspvdb` against the real USPVDB download~~ — **done** (see
  `docs/plans/data-bootstrap.md`): USPVDB v4.0's 6,611 facilities load in ~7 s, re-runs are
  idempotent, and none of the columns we use has nulls or sentinel values, so the
  "missing `name`/`state`/`capacity_mw` aborts the whole load" concern didn't materialize
  (it could still with a future release). Migration `0002` adds `case_id` with
  `default=0, unique=True`, which is fine on an empty table only.
- The real data showed `/api/facilities/` returns ~25 MB — tracked in
  `docs/plans/vector-tile-map.md`.
- Use a tile provider (or self-host) before deploying or heavy use; the public OSM server
  is best-effort with no SLA.
- Local database volumes created by the old `postgis/postgis` image must be recreated
  (`docker compose down -v`) because of the glibc collation change.
- Deferred items below (Next.js, spatial joins, raw-SQL KNN).

## Deferred to a later pass (not in this slice)

- Next.js frontend (requirements.md leaves this as a later phase).
- Spatial join against forest-loss/protected-area data (stretch goal).
- Raw-SQL KNN (`<->`) performance comparison (open question in requirements.md).
