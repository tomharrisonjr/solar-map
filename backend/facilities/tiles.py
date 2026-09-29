"""Mapbox Vector Tiles built directly in PostGIS.

MapLibre asks for `/tiles/{z}/{x}/{y}.mvt` and only fetches what is in view, instead of
downloading every facility polygon up front. PostGIS does the whole job in one query:

* `ST_TileEnvelope(z, x, y)` — the tile's bounding box in Web Mercator (EPSG:3857).
* `f.geom && <envelope in 4326>` — bbox filter against the GiST index. Facilities are stored
  in EPSG:4326, so we transform the *one* envelope to 4326 and compare (using the index)
  rather than transforming every row to 3857 (which would defeat the index).
* `ST_AsMVTGeom` — transform the matches to 3857, clip to the tile and snap to its integer grid.
* `ST_AsMVT` — encode the rows as one MVT layer. Layers are simply concatenated (`||`).

Two layers: `points` (the denormalized `centroid`, at every zoom, so facilities stay visible
when they are smaller than a pixel) and `polygons` (the real `geom`, only from
`POLYGON_MIN_ZOOM` up, where a panel array is large enough to see).
"""

from __future__ import annotations

from django.db import connection

MAX_ZOOM: int = 22
# Below this zoom a panel array is smaller than a pixel, so only centroid points are sent.
POLYGON_MIN_ZOOM: int = 9
MVT_EXTENT: int = 4096  # tile grid resolution (the spec default)
MVT_BUFFER: int = 64  # grid units of geometry kept outside the tile edge, so lines/fills don't clip
MVT_CONTENT_TYPE: str = "application/vnd.mapbox-vector-tile"

# All SQL is static text; z/x/y and the constants above are bound as parameters.
_POINTS_CTE = """
points AS (
    SELECT f.id, f.case_id, f.name, f.state, f.capacity_mw, f.install_year,
           ST_AsMVTGeom(
               ST_Transform(f.centroid, 3857), tile.env, %(extent)s, %(buffer)s, true
           ) AS geom
    FROM facilities_solarfacility AS f, tile
    WHERE f.centroid && tile.env_4326
)
"""

_POLYGONS_CTE = """
polygons AS (
    SELECT f.id, f.case_id, f.name, f.state, f.capacity_mw, f.install_year,
           ST_AsMVTGeom(
               ST_Transform(f.geom, 3857), tile.env, %(extent)s, %(buffer)s, true
           ) AS geom
    FROM facilities_solarfacility AS f, tile
    WHERE f.geom && tile.env_4326
)
"""

_TILE_CTE = """
WITH tile AS (
    SELECT env, ST_Transform(env, 4326) AS env_4326
    FROM (SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env) AS e
),
"""

_POINTS_ONLY_SQL = (
    _TILE_CTE
    + _POINTS_CTE
    + """
SELECT COALESCE((SELECT ST_AsMVT(points.*, 'points', %(extent)s, 'geom') FROM points), ''::bytea)
"""
)

_POINTS_AND_POLYGONS_SQL = (
    _TILE_CTE
    + _POINTS_CTE
    + ","
    + _POLYGONS_CTE
    + """
SELECT COALESCE(
           (SELECT ST_AsMVT(points.*, 'points', %(extent)s, 'geom') FROM points), ''::bytea
       )
    || COALESCE(
           (SELECT ST_AsMVT(polygons.*, 'polygons', %(extent)s, 'geom') FROM polygons), ''::bytea
       )
"""
)


def is_valid_tile(z: int, x: int, y: int) -> bool:
    """True if (z, x, y) addresses a real tile: 0 <= z <= MAX_ZOOM and 0 <= x, y < 2**z."""
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


def build_tile(z: int, x: int, y: int) -> bytes:
    """Return the MVT bytes for a tile, or `b""` if no facility falls in it."""
    sql = _POINTS_AND_POLYGONS_SQL if z >= POLYGON_MIN_ZOOM else _POINTS_ONLY_SQL
    params = {"z": z, "x": x, "y": y, "extent": MVT_EXTENT, "buffer": MVT_BUFFER}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return bytes(row[0]) if row and row[0] else b""
