# Vector-tile map (ST_AsMVT) instead of a 24.8 MB list

- GitHub Issue: #15
- Date: 2026-09-29
- Status: In Progress

## Steps

| Status | # | Step |
|--------|---|------|
| ✅ Done | 1 | MVT tile endpoint (`/tiles/{z}/{x}/{y}.mvt`) |
| ✅ Done | 2 | Map uses the vector source; restore list pagination |
| ⬜ Pending | 3 | Measure, tune, wrap-up |

## Context

Measured with the real USPVDB data (6,611 facilities): `/api/facilities/` returns **24.8 MB**
(3.2 s locally, uncompressed; ~9.5 MB gzipped) because the ingestion-plan Step 2 made the list
unpaginated on the assumption of "a few thousand small rows" — polygons average ~3.7 KB each.
`/nearest/` is fine (8.6 KB, 0.16 s). Chosen fix: serve **Mapbox Vector Tiles straight from
PostGIS** (`ST_TileEnvelope` + `ST_AsMVTGeom` + `ST_AsMVT`, PostGIS 3.4 in our image) so
MapLibre fetches only what is in view. No new dependencies; strong PostGIS learning value.

Do `docs/plans/data-bootstrap.md` first: this plan's verification needs the real dataset that
plan makes easy to load.

## Step 1 — MVT tile endpoint (#25)

- New view + URL: `GET /tiles/<int:z>/<int:x>/<int:y>.mvt` (wire in `config/urls.py`; view in
  `facilities/views.py` or a new `facilities/tiles.py`). Validate `0 ≤ z ≤ 22`,
  `0 ≤ x,y < 2^z` → 404 otherwise.
- Raw SQL via `django.db.connection.cursor()`, parameterized. Filter in the storage SRS first
  so the GiST index on `geom` is used (`f.geom && ST_Transform(ST_TileEnvelope(z,x,y), 4326)`),
  transform only matches to 3857, then `ST_AsMVTGeom(..., 4096, 64, true)` and `ST_AsMVT`.
  Two layers per tile: `points` from the denormalized `centroid` column (always; repo
  convention: don't recompute centroids ad hoc) and `polygons` from `geom` only at
  `z ≥ POLYGON_MIN_ZOOM` (start at 9; tune in step 3). Properties: id, case_id, name, state,
  capacity_mw, install_year only.
- Response: `application/vnd.mapbox-vector-tile`, 204 for empty tiles, `Cache-Control:
  public, max-age=3600`. Add `GZipMiddleware` (settings) so tiles/API compress.
- Tests: tile with data → 200 + correct content type + non-empty body; empty tile → 204;
  out-of-range z/x/y → 404; low zoom includes no polygon layer / high zoom does (compare
  helper-level feature counts via SQL, no MVT-decoding dependency).
- Confirm a GiST index exists on `geom` (GeoDjango `spatial_index=True` default → check
  migration 0001) and record `EXPLAIN` showing an index scan.

**As shipped:**

- `facilities/tiles.py` (static parameterized SQL, `is_valid_tile`, `build_tile`) and a
  `tile_view` in `facilities/views.py` (`@require_GET`, `@cache_control(public, max_age=3600)`),
  wired at `tiles/<z>/<x>/<y>.mvt` in `config/urls.py`. 404 for invalid coordinates, 204 for a
  valid tile with no facilities, `application/vnd.mapbox-vector-tile` otherwise. Constants:
  `MAX_ZOOM = 22`, `POLYGON_MIN_ZOOM = 9`, extent 4096, buffer 64.
- `GZipMiddleware` added first in `MIDDLEWARE`.
- 8 new tests (24 total): layers per zoom (points-only below `POLYGON_MIN_ZOOM`, both at and
  above), 204/404/405, cache headers, gzip, `is_valid_tile`. Tile bytes are protobuf with
  plain-text layer names/strings, so tests assert on those, no decoding dependency.
- **Index confirmed (real data, 6,611 rows):** GeoDjango creates GiST indexes on both `geom` and
  `centroid` (`pg_indexes`). `EXPLAIN (ANALYZE)` of the tile query shows an **Index Scan** on the
  GiST index by default (no forcing), ~0.1 ms, 4 buffers for a z12 tile. The tile envelope is
  constant-folded into a literal polygon, which is what lets the index be used.
- **Measured against the real data** (local, ~20–70 ms per tile):

  | Tile | Layers | Bytes | gzip |
  | --- | --- | --- | --- |
  | 0/0/0 (whole world) | points only | 438,359 | 202,038 |
  | 4/3/6 | points only | 48,198 | — |
  | 8/43/102 (LA area) | points only | 3,541 | — |
  | 9/87/204 (LA area) | points + polygons | 8,888 | — |
  | 12/702/1635 | points + polygons | 962 | 752 |

  For comparison the list API is 24.8 MB (8.7 MB gzipped) — a viewport now needs a few KB.
- **For Step 3:** the world tile is the outlier (438 KB, every facility's properties). Options
  to try: drop properties from the `points` layer at low zoom (keep just id), or thin points
  below a zoom threshold. Also tune `POLYGON_MIN_ZOOM` in a browser.

## Step 2 — Map uses the vector source; restore list pagination (#27)

- `backend/facilities/static/facilities/map.js`: replace the GeoJSON `facilities` source with
  `{type: "vector", tiles: [<origin>/tiles/{z}/{x}/{y}.mvt], maxzoom: 14}` (MapLibre needs
  absolute tile URLs → build from `location.origin`); fill/outline layers on `polygons`
  (minzoom `POLYGON_MIN_ZOOM`), circle layer on `points` (maxzoom same). Nearest results and
  highlight remain GeoJSON via `/nearest/`. Drop the up-front `loadFacilities()` fetch; update
  status text ("Click the map to find the nearest").
- `backend/facilities/templates/facilities/map.html`: config gets `tilesPath`.
- `views.py`: remove `pagination_class = None` from `SolarFacilityViewSet` so the list is
  paginated again (a 24.8 MB endpoint shouldn't exist); update its test to expect a paged
  FeatureCollection. Rework the Node simulation harness for a vector source (scratch only).
- Keep OSM tile-policy constraints intact (Referrer-Policy, attribution).
- **Added scope (requested when starting this step):** if the browser shares its location, open
  the map zoomed to a 100 km radius around the user.

**As shipped:**

- `map.js`: the `facilities` source is now `{type: "vector", tiles: [origin + tilesPath],
  maxzoom: 14}` (URL built by string concatenation — `new URL()` would percent-encode the
  `{z}/{x}/{y}` braces); a `points` circle layer below `polygonMinZoom` and `polygons`
  fill/outline layers from it. `loadFacilities()` and the up-front fetch are gone; nearest
  results and highlighting are unchanged (GeoJSON via `/nearest/`).
- `map.html` config: `tilesPath`, `tilesMaxZoom`, `polygonMinZoom` (rendered from
  `MapView.get_context_data`, the same `POLYGON_MIN_ZOOM` constant the tile SQL uses — vector
  sources default to 512 px tiles, so tile zoom = floor(map zoom) and the two thresholds line
  up), `nearestUrl`, `nearestCount`, `userRadiusKm: 100`. `facilitiesUrl` removed.
- **List pagination restored:** `FacilityPagination` (a `GeoJsonPagination` subclass: 100 per
  page, `?page_size=` up to 1000) keeps the response a valid GeoJSON `FeatureCollection` with
  `count`/`next`/`previous`; the queryset is ordered by `id` so pages are stable.
  A default page is 184 KB in ~43 ms (was 24.8 MB).
- **Browser location → 100 km view:** `navigator.geolocation` (browser-side only; position is
  sent to the server only if the user clicks). On success, `fitBounds` to the 200 km square
  around the user (no animation), plus a green "you are here" marker. Falls back to the
  whole-US view when denied/unavailable, ignores locations outside US coverage (the data is
  US-only), and doesn't move the view if the user has already clicked the map before the fix
  arrives. Requires HTTPS or `localhost`.
- README: the "known limitation" note is gone; API table documents the paged list and the tile
  endpoint; new troubleshooting row for location.
- Tests (29 total): paged list, `page_size` and its cap, the page's tile path stays in step with
  the route, `polygonMinZoom` comes from the server constant, the 100 km setting.
- **Verified:** `task check`; the real `map.js` run under Node with a stubbed MapLibre and a
  controllable geolocation against the live server — 26 checks across vector source/layer
  config, no list fetch, exact 200 km box centred on the user, denied/timeout/outside-US/
  Alaska/Hawaii, and click-before-fix. **Not verified:** actual in-browser rendering, tile
  loading and the real permission prompt — needs a look at the page.
- **First-load transfer, real data (before → after):** default US view (4 tiles at z3)
  ≈ 0.43 MB, 0.21 MB gzipped, vs 24.8 MB (8.7 MB gzipped) — ~58× smaller; a 100 km view around
  Los Angeles (z8) ≈ 11 KB vs 24.8 MB.

## Step 3 — Measure, tune, wrap-up

- Record with real data: tile size/time at z=3, 6, 9, 12; total initial bytes before/after;
  tune `POLYGON_MIN_ZOOM`, `maxzoom`, cache age.
- Docs: `docs/requirements.md` (architecture/stack + the corrected "thousands of rows" claim),
  `AGENTS.md` conventions (tile endpoint, SQL parameterization), plan `Status: Complete`,
  update the ingestion plan's Step 2/3 notes to point here.
- `task check` passes.

## Verification

`task check`. Real data via `data-bootstrap` (`task setup`): load the page in a browser —
initial network transfer is small, pan/zoom fetches `.mvt` tiles, polygons appear from the
tuned zoom, click still highlights nearest; `curl -s -o /dev/null -w '%{size_download}'` on
sample tiles; `EXPLAIN (ANALYZE)` on the tile SQL shows an index scan.

## Deferred to a later pass (not in this slice)

- Search box, bbox filter API.
- Tile caching layer (e.g. CDN / pre-generated tiles).
- Switching the OSM basemap to a tile provider.
