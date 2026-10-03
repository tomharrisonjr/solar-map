# Solar Map — Requirements

## Purpose

A small personal project to gain hands-on experience with PostGIS, GeoDjango, and spatial
querying, oriented around an environment/climate/energy theme. Secondary goal: build
familiarity with the kind of geospatial data work relevant to satellite-based
deforestation-monitoring roles (spatial joins, geometry types, KNN queries) without
attempting that domain directly.

## Goals

- Learn PostGIS fundamentals: geometry columns, spatial indexes (GiST), spatial joins,
  distance/KNN queries, area/containment operations.
- Learn GeoDjango: spatial model fields, `LayerMapping`/ingestion commands, GeoDjango ORM
  spatial lookups and annotations.
- Ship something small but real: load a public solar-farm dataset, expose it via an API,
  and answer "what's the nearest solar farm to this point?" (and similar spatial questions).
- Get experience deploying a containerized Django app against a managed Postgres/PostGIS
  instance on AWS.

## Non-goals (for v1)

- Not attempting actual satellite imagery analysis or deforestation detection.
- Not building a polished, public-facing product — this is a learning project.
- Not committing to global data coverage; starting US-only is fine.

## Dataset

**Primary: USPVDB — USGS/LBNL United States Large-Scale Solar Photovoltaic Database**

- Locations and digitized panel-array polygons for US ground-mounted solar facilities
  ≥ 1 MW capacity, verified against high-resolution aerial imagery.
- Available as Shapefile, GeoJSON, CSV, and a REST API.
- Chosen over alternatives because it ships real polygon geometry (not just points),
  enabling `ST_Area`, `ST_Centroid`, `ST_Contains`, and other containment/area operations
  in addition to distance queries.

**Considered alternatives:**

- *WRI Global Power Plant Database* — ~35,000 power plants globally, CC-BY-4.0, point
  geometry only, last actively maintained ~early 2022. Good fallback if global coverage
  becomes a priority; simpler (points-only) means it mainly supports distance/KNN queries.
- *OpenStreetMap via Overpass API* (`power=plant` + `plant:source=solar`) — live,
  community-maintained, global, but uneven coverage. Interesting as a live-query exercise
  but not the primary source for v1.

**Possible future pairing (stretch goal):** Global Forest Watch / Hansen Global Forest
Change (tree cover loss) or the World Database on Protected Areas (WDPA), to support a
more thematically-relevant spatial join exercise — e.g., "solar farms sited within X km of
protected areas or recent forest-loss areas." This is closer to the deforestation-detection
skillset and could be a v2 direction once the core app works.

## Core Features (v1)

All four are implemented (see `docs/plans/uspvdb-ingestion-and-map-ui.md`).

1. ✅ **Data ingestion**: management command to load USPVDB GeoJSON into the database,
   including computing/storing a denormalized centroid point per facility.
   *`load_uspvdb [<path-or-url>]` upserts by `case_id`. With no argument it downloads the
   official USGS zip itself and loads the versioned `.geojson` inside (a local file or URL,
   zip or bare GeoJSON, also works); `task setup` / `task data:load` wrap it. Run against
   the full real dataset (6,611 facilities, ~7 s). The data is not committed. Upsert never
   deletes facilities that USGS later removes (a `--prune` flag is deferred).*
2. ✅ **Nearest-facility query**: given a lat/lon, return the N closest solar facilities
   (via GeoDjango ORM `Distance` annotation initially; consider raw SQL with the PostGIS
   `<->` KNN operator later for performance comparison).
   *`GET /api/facilities/nearest/?lat=&lon=&n=` (default 5, max 25) via the ORM annotation;
   the raw-SQL KNN comparison is still open.*
3. ✅ **API layer**: expose facilities as GeoJSON via Django REST Framework +
   `djangorestframework-gis`, suitable for consumption by a map-based frontend.
   *`/api/facilities/` is a paged GeoJSON FeatureCollection (100/page, `?page_size=` up to
   1000). The map doesn't use it: it reads vector tiles from `/tiles/{z}/{x}/{y}.mvt`, built in
   PostGIS with `ST_AsMVT` (see `docs/plans/vector-tile-map.md`). The full polygon set is
   ~25 MB, so it must not be sent in one response.*
4. ✅ **Basic map UI**: display facilities on a map and let a user click/search a location to
   find the nearest facility (or facilities). *Shipped as a minimal server-rendered page at
   `/` (MapLibre GL JS from a CDN): facilities stream in as vector tiles (dots when zoomed
   out, polygons from zoom 9; ~57 KB for the default US view), the map opens on a 100 km view
   around the user if the browser shares its location, and clicking finds the nearest
   facilities. No search box yet.*

## Stretch Features

- Spatial join against forest-loss or protected-area data (see dataset section above).
- Area/containment queries using the panel-array polygons (e.g., total solar capacity
  area within a bounding region).
- Swap in OpenStreetMap or WRI data as an additional/comparison data source.

## Architecture

### Repo layout

```
solar-map/
├── docker-compose.yml          # imresamu/postgis (multi-arch) image for local dev
├── Taskfile.yml                # task check / lint / test / migrate, wt:new / wt:rm (worktrees)
├── AGENTS.md                   # agent + contributor guidance (CLAUDE.md symlinks to it)
├── backend/
│   ├── Dockerfile
│   ├── manage.py
│   ├── config/                 # Django project settings
│   │   ├── settings.py
│   │   └── urls.py
│   ├── facilities/             # main app
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── tiles.py            # PostGIS-built vector tiles (ST_AsMVT) for /tiles/{z}/{x}/{y}.mvt
│   │   ├── templates/facilities/map.html   # minimal map page (served at /)
│   │   ├── static/facilities/map.js        # MapLibre map + nearest-facility sidebar
│   │   └── management/commands/
│   │       └── load_uspvdb.py  # data ingestion
│   └── requirements.txt
└── frontend/                   # optional Next.js later
```

### Stack

- **Backend**: Python 3.14, Django 5.2 LTS (5.2.8+ is the first with 3.14 support),
  GeoDjango, PostGIS (via the multi-arch `imresamu/postgis` Docker image locally — the
  official `postgis/postgis` is amd64-only; AWS RDS for Postgres with the PostGIS extension
  enabled in production).
- **API**: Django REST Framework + `djangorestframework-gis` for GeoJSON serialization
  (paged list, nearest-facility query), plus a plain Django view that serves Mapbox Vector
  Tiles generated by PostGIS (`ST_TileEnvelope` + `ST_AsMVTGeom` + `ST_AsMVT`) — no tile
  server or extra dependency.
- **Frontend**: optional Next.js app using MapLibre/Mapbox GL, consuming the GeoJSON API.
  Started with a minimal server-rendered template (`facilities/map.html`, MapLibre GL JS
  via CDN, no build step); Next.js can come later.
- **Hosting**: AWS. Containerized Django app (pattern consistent with existing personal
  AWS/ECS/Terraform setup); Postgres/PostGIS on RDS rather than in-container, since RDS
  supports the PostGIS extension directly.

### Data model (initial sketch)

```python
from django.contrib.gis.db import models

class SolarFacility(models.Model):
    case_id = models.IntegerField(unique=True)   # stable USPVDB id; the upsert key
    eia_id = models.CharField(max_length=20, unique=True, null=True)
    name = models.CharField(max_length=255)
    state = models.CharField(max_length=2)
    capacity_mw = models.FloatField()
    install_year = models.IntegerField(null=True)
    geom = models.MultiPolygonField(srid=4326)   # USPVDB panel-array polygons
    centroid = models.PointField(srid=4326, null=True)  # denormalized for fast KNN

    class Meta:
        indexes = [models.Index(fields=["state"])]
```

The centroid is denormalized on ingestion so nearest-facility queries can run against
points rather than polygons, which is cheaper and simpler, while `geom` remains available
for area/containment work.

`case_id` was added during ingestion work: it is always present and unique in USPVDB,
whereas `eia_id` is nullable (not every facility links to an EIA plant), so `eia_id` can't
serve as the idempotency key for re-loading the dataset.

### Example nearest-facility query (GeoDjango ORM)

```python
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point

pt = Point(lng, lat, srid=4326)
SolarFacility.objects.annotate(distance=Distance("centroid", pt)).order_by("distance")[:5]
```

## Known Risks / Friction Points

- **GDAL/GEOS system libraries**: the most common early friction point with GeoDjango.
  If `manage.py migrate` or `LayerMapping` import fails with missing library errors,
  check `GDAL_LIBRARY_PATH` / `GEOS_LIBRARY_PATH` in Django settings first, and verify the
  Docker base image includes the GDAL/GEOS system packages.
- **Local vs. RDS parity**: use the multi-arch `imresamu/postgis` Docker image locally (not
  plain `postgres`; the official `postgis/postgis` is amd64-only) so the extension is
  available from the start; remember to run `CREATE EXTENSION postgis;` on the RDS
  instance before first migration.
- **Basemap tile provider**: the map uses Stadia Maps' Alidade Smooth raster tiles (free tier:
  200k credits/month, **non-commercial use only**; domain-authenticated via the browser's
  `Origin`/`Referer`, so `SECURE_REFERRER_POLICY` must stay non-restrictive and the deployed
  domain must be registered in Stadia's dashboard). The provider is configured by `BASEMAP_*`
  env vars, so moving to MapTiler or self-hosted tiles is a config change; revisit before any
  commercial use.
- Dataset licensing/attribution: confirm USPVDB and any paired datasets (GFW, WDPA) usage
  terms if the project is ever made public.

## Open Questions

- How far to take the frontend (minimal map view vs. full Next.js app)?
- Whether to pursue the forest-loss/protected-area spatial join as a v2 milestone.
- Whether performance work (raw SQL KNN via `<->`) is worth doing. The dataset is small in
  rows (6,611 facilities; the nearest query takes ~0.2 s over HTTP) but not small in bytes:
  its polygons are ~25 MB as GeoJSON, which is why the map uses vector tiles. KNN would be
  purely for learning purposes at this size.
