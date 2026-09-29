"""Mapbox Vector Tiles built directly in PostGIS.

MapLibre asks for `/tiles/{z}/{x}/{y}.mvt` and only fetches what is in view, instead of
downloading every facility polygon up front. PostGIS does the whole job in one query:

* `ST_TileEnvelope(z, x, y)` — the tile's bounding box in Web Mercator (EPSG:3857).
* `f.geom && <envelope in 4326>` — bbox filter against the GiST index. Facilities are stored
  in EPSG:4326, so we transform the *one* envelope to 4326 and compare (using the index)
  rather than transforming every row to 3857 (which would defeat the index).
* `ST_AsMVTGeom` — transform the matches to 3857, clip to the tile and snap to its integer grid.
* `ST_AsMVT` — encode the rows as one MVT layer.

The two layers are disjoint by zoom, matching exactly what the map draws:

* below `POLYGON_MIN_ZOOM`: a `points` layer — one dot per facility centroid (the denormalized
  `centroid` column), carrying only `id` and thinned to at most one dot per `POINT_CELL` grid
  cells (~1 screen pixel), largest facility winning a cell;
* from `POLYGON_MIN_ZOOM` up: a `polygons` layer — the real panel-array `geom` with its details.

Why these numbers (USPVDB v4.0, 6,611 facilities; measured over every tile that has a facility):
median footprint is ~60,000 m² (~245 m across), i.e. ~1 px at zoom 8 but ~2 px at zoom 9 (512 px
tiles), so polygons only become worth drawing at 9. The whole-world tile was 438 KB with six
properties per dot; `id`-only is 139 KB and thinning to one dot per pixel cell brings it to
~13 KB (958 dots), while sending each facility once (not as both a dot and a polygon) shrinks
the polygon tiles by about a third. See docs/plans/vector-tile-map.md for the full tables.
"""

from __future__ import annotations

from django.db import connection

MAX_ZOOM: int = 22
# Below this zoom a median panel array is ~1 px or less, so only centroid dots are sent.
POLYGON_MIN_ZOOM: int = 9
MVT_EXTENT: int = 4096  # tile grid resolution (the spec default)
MVT_BUFFER: int = 64  # grid units of geometry kept outside the tile edge, so lines/fills don't clip
# Dots closer than this many grid units collapse to one. A 512 px tile spans MVT_EXTENT units, so
# 8 units is ~1 px; the map's dots are 3 px wide, so the thinning is visually invisible.
POINT_CELL: int = 8
MVT_CONTENT_TYPE: str = "application/vnd.mapbox-vector-tile"

# All SQL is static text; z/x/y and the constants above are bound as parameters.
_TILE_CTE = """
WITH tile AS (
    SELECT env, ST_Transform(env, 4326) AS env_4326
    FROM (SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env) AS e
)
"""

# One dot per POINT_CELL x POINT_CELL grid cell: DISTINCT ON the cell, largest capacity first.
_POINTS_SQL = (
    _TILE_CTE
    + """
, points AS (
    SELECT DISTINCT ON (floor(ST_X(g.geom) / %(cell)s), floor(ST_Y(g.geom) / %(cell)s))
           g.id, g.geom
    FROM (
        SELECT f.id, f.capacity_mw,
               ST_AsMVTGeom(
                   ST_Transform(f.centroid, 3857), tile.env, %(extent)s, %(buffer)s, true
               ) AS geom
        FROM facilities_solarfacility AS f, tile
        WHERE f.centroid && tile.env_4326
    ) AS g
    WHERE g.geom IS NOT NULL
    ORDER BY floor(ST_X(g.geom) / %(cell)s), floor(ST_Y(g.geom) / %(cell)s), g.capacity_mw DESC
)
SELECT COALESCE(
    (SELECT ST_AsMVT(points.*, 'points', %(extent)s, 'geom', 'id') FROM points), ''::bytea
)
"""
)

_POLYGONS_SQL = (
    _TILE_CTE
    + """
, polygons AS (
    SELECT f.id, f.case_id, f.name, f.state, f.capacity_mw, f.install_year,
           ST_AsMVTGeom(
               ST_Transform(f.geom, 3857), tile.env, %(extent)s, %(buffer)s, true
           ) AS geom
    FROM facilities_solarfacility AS f, tile
    WHERE f.geom && tile.env_4326
)
SELECT COALESCE(
    (SELECT ST_AsMVT(polygons.*, 'polygons', %(extent)s, 'geom', 'id') FROM polygons), ''::bytea
)
"""
)


def is_valid_tile(z: int, x: int, y: int) -> bool:
    """True if (z, x, y) addresses a real tile: 0 <= z <= MAX_ZOOM and 0 <= x, y < 2**z."""
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


def build_tile(z: int, x: int, y: int) -> bytes:
    """Return the MVT bytes for a tile, or `b""` if no facility falls in it."""
    sql = _POLYGONS_SQL if z >= POLYGON_MIN_ZOOM else _POINTS_SQL
    params = {
        "z": z,
        "x": x,
        "y": y,
        "extent": MVT_EXTENT,
        "buffer": MVT_BUFFER,
        "cell": POINT_CELL,
    }
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return bytes(row[0]) if row and row[0] else b""
