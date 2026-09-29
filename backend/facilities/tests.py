import io
import json
import math
import tempfile
import urllib.error
import zipfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from facilities.management.commands.load_uspvdb import (
    DEFAULT_SOURCE,
    DOWNLOAD_TIMEOUT_SECONDS,
    USER_AGENT,
)
from facilities.models import SolarFacility
from facilities.tiles import MAX_ZOOM, MVT_CONTENT_TYPE, POLYGON_MIN_ZOOM, is_valid_tile
from facilities.views import FacilityPagination


class SolarFacilityModelTests(TestCase):
    def test_str_returns_name(self) -> None:
        polygon = Polygon(((-1, -1), (-1, 1), (1, 1), (1, -1), (-1, -1)))
        facility = SolarFacility.objects.create(
            case_id=1,
            name="Test Solar Farm",
            state="CA",
            capacity_mw=10.0,
            geom=MultiPolygon(polygon),
            centroid=Point(0, 0),
        )

        self.assertEqual(str(facility), "Test Solar Farm")


class NearestFacilityApiTests(TestCase):
    url: str = "/api/facilities/nearest/"

    @classmethod
    def setUpTestData(cls) -> None:
        # Centroids along the equator at lon 0, 1, 2 so distance order is unambiguous.
        for case_id, (name, lon) in enumerate([("Far", 2.0), ("Near", 0.0), ("Mid", 1.0)], start=1):
            polygon = Polygon(
                (
                    (lon - 0.1, -0.1),
                    (lon - 0.1, 0.1),
                    (lon + 0.1, 0.1),
                    (lon + 0.1, -0.1),
                    (lon - 0.1, -0.1),
                )
            )
            SolarFacility.objects.create(
                case_id=case_id,
                name=name,
                state="CA",
                capacity_mw=1.0,
                geom=MultiPolygon(polygon),
                centroid=Point(lon, 0),
            )

    def test_orders_by_distance_and_includes_distance(self) -> None:
        response = self.client.get(self.url, {"lat": 0.0, "lon": 0.1})

        self.assertEqual(response.status_code, 200)
        features = response.json()["features"]
        self.assertEqual([f["properties"]["name"] for f in features], ["Near", "Mid", "Far"])
        distances = [f["properties"]["distance_m"] for f in features]
        self.assertEqual(distances, sorted(distances))

    def test_n_limits_results(self) -> None:
        response = self.client.get(self.url, {"lat": 0, "lon": 0, "n": 2})

        self.assertEqual(len(response.json()["features"]), 2)

    def test_missing_or_invalid_params_return_400(self) -> None:
        for params in [
            {},
            {"lat": 0},
            {"lon": 0},
            {"lat": "abc", "lon": 0},
            {"lat": 91, "lon": 0},
            {"lat": 0, "lon": 181},
            {"lat": "nan", "lon": 0},
            {"lat": 0, "lon": 0, "n": 0},
            {"lat": 0, "lon": 0, "n": 26},
            {"lat": 0, "lon": 0, "n": "x"},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)

    def test_list_is_a_paginated_feature_collection(self) -> None:
        body = self.client.get("/api/facilities/").json()

        # Still valid GeoJSON, plus paging info; everything fits on one default page here.
        self.assertEqual(body["type"], "FeatureCollection")
        self.assertEqual(body["count"], 3)
        self.assertEqual(len(body["features"]), 3)
        self.assertIsNone(body["next"])

    def test_list_pages_with_page_size(self) -> None:
        first = self.client.get("/api/facilities/", {"page_size": 2}).json()
        second = self.client.get("/api/facilities/", {"page_size": 2, "page": 2}).json()

        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["features"]), 2)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(second["features"]), 1)
        self.assertIsNone(second["next"])
        ids = [f["id"] for f in first["features"] + second["features"]]
        self.assertEqual(ids, sorted(ids))  # stable order, no repeats
        self.assertEqual(len(set(ids)), 3)

    def test_list_page_size_is_capped(self) -> None:
        body = self.client.get("/api/facilities/", {"page_size": 100000}).json()

        # max_page_size caps it; the 3 test rows still all fit.
        self.assertEqual(len(body["features"]), 3)
        self.assertLessEqual(len(body["features"]), FacilityPagination.max_page_size)


class LoadUspvdbCommandTests(TestCase):
    def _feature(
        self,
        case_id: int,
        name: str = "Test Solar Farm",
        eia_id: int | None = None,
    ) -> dict:
        return {
            "type": "Feature",
            "properties": {
                "case_id": case_id,
                "eia_id": eia_id,
                "p_name": name,
                "p_state": "CA",
                "p_cap_ac": 10.5,
                "p_year": 2020,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1, -1], [-1, 1], [1, 1], [1, -1], [-1, -1]]],
            },
        }

    def test_creates_and_updates_facilities_from_geojson_file(self) -> None:
        geojson = {"type": "FeatureCollection", "features": [self._feature(case_id=42)]}
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "uspvdb.geojson"
            path.write_text(json.dumps(geojson))

            call_command("load_uspvdb", str(path), stdout=StringIO())

            facility = SolarFacility.objects.get(case_id=42)
            self.assertEqual(facility.name, "Test Solar Farm")
            self.assertEqual(facility.state, "CA")
            self.assertEqual(facility.capacity_mw, 10.5)
            self.assertEqual(facility.install_year, 2020)
            self.assertIsNone(facility.eia_id)
            self.assertIsNotNone(facility.centroid)
            self.assertEqual(SolarFacility.objects.count(), 1)

            geojson["features"][0]["properties"]["p_name"] = "Renamed Solar Farm"
            geojson["features"][0]["properties"]["eia_id"] = 12345
            path.write_text(json.dumps(geojson))

            call_command("load_uspvdb", str(path), stdout=StringIO())

            self.assertEqual(SolarFacility.objects.count(), 1)
            facility.refresh_from_db()
            self.assertEqual(facility.name, "Renamed Solar Farm")
            self.assertEqual(facility.eia_id, "12345")

    def _collection_bytes(self, *case_ids: int) -> bytes:
        features = [self._feature(case_id=case_id) for case_id in case_ids]
        return json.dumps({"type": "FeatureCollection", "features": features}).encode()

    def _zip_bytes(self, files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    def test_loads_versioned_geojson_from_official_style_zip(self) -> None:
        # Mirrors the real release: CHANGELOG + XML metadata + a *versioned* .geojson name.
        raw = self._zip_bytes(
            {
                "CHANGELOG.txt": b"changes",
                "uspvdb_v9_9_20990101.geojson": self._collection_bytes(1, 2),
                "uspvdb_v9_9_20990101.xml": b"<metadata/>",
            }
        )
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "uspvdbGeoJSON.zip"
            path.write_bytes(raw)

            call_command("load_uspvdb", str(path), stdout=out)

        self.assertEqual(SolarFacility.objects.count(), 2)
        self.assertIn("uspvdb_v9_9_20990101.geojson", out.getvalue())
        self.assertIn("Please cite: Fujita", out.getvalue())

    def test_zip_without_geojson_raises_command_error(self) -> None:
        raw = self._zip_bytes({"CHANGELOG.txt": b"changes"})
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "empty.zip"
            path.write_bytes(raw)

            with self.assertRaisesMessage(CommandError, "found 0"):
                call_command("load_uspvdb", str(path), stdout=StringIO())

        self.assertEqual(SolarFacility.objects.count(), 0)

    def test_zip_with_several_geojson_files_raises_command_error(self) -> None:
        raw = self._zip_bytes(
            {"a.geojson": self._collection_bytes(1), "b.geojson": self._collection_bytes(2)}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "two.zip"
            path.write_bytes(raw)

            with self.assertRaisesMessage(CommandError, "found 2"):
                call_command("load_uspvdb", str(path), stdout=StringIO())

        self.assertEqual(SolarFacility.objects.count(), 0)

    def test_defaults_to_official_url_when_source_omitted(self) -> None:
        raw = self._zip_bytes({"uspvdb_v9_9_20990101.geojson": self._collection_bytes(7)})
        with patch("facilities.management.commands.load_uspvdb.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = raw

            call_command("load_uspvdb", stdout=StringIO())

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, DEFAULT_SOURCE)
        # USGS returns 403 to Python's default urllib agent, so we must identify the app.
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], DOWNLOAD_TIMEOUT_SECONDS)
        self.assertTrue(SolarFacility.objects.filter(case_id=7).exists())

    def test_download_failure_raises_command_error(self) -> None:
        with patch(
            "facilities.management.commands.load_uspvdb.urllib.request.urlopen",
            side_effect=urllib.error.URLError("no route"),
        ):
            with self.assertRaisesMessage(CommandError, "Could not download"):
                call_command("load_uspvdb", stdout=StringIO())

    def test_missing_local_file_raises_command_error(self) -> None:
        with self.assertRaisesMessage(CommandError, "Could not read"):
            call_command("load_uspvdb", "/nonexistent/uspvdb.geojson", stdout=StringIO())

    def test_non_geojson_content_raises_command_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            not_json = Path(tmp_dir) / "bad.geojson"
            not_json.write_text("<html>oops</html>")
            no_features = Path(tmp_dir) / "empty.geojson"
            no_features.write_text('{"type": "Feature"}')

            with self.assertRaisesMessage(CommandError, "not valid JSON"):
                call_command("load_uspvdb", str(not_json), stdout=StringIO())
            with self.assertRaisesMessage(CommandError, "FeatureCollection"):
                call_command("load_uspvdb", str(no_features), stdout=StringIO())


class MapViewTests(TestCase):
    def test_root_renders_map_page(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "facilities/map.html")
        self.assertContains(response, 'id="map"')
        self.assertContains(response, "/static/facilities/map.js")

    def test_page_loads_facilities_as_vector_tiles_not_the_full_list(self) -> None:
        response = self.client.get("/")

        # The tile path written into the page must be the route the server actually serves.
        self.assertContains(response, 'tilesPath: "/tiles/{z}/{x}/{y}.mvt"')
        self.assertEqual(reverse("tile", args=(3, 4, 5)), "/tiles/3/4/5.mvt")
        # ...and the map must no longer be told to fetch every facility up front.
        self.assertNotContains(response, "facilitiesUrl")

    def test_page_polygon_min_zoom_comes_from_the_server_constant(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.context["polygon_min_zoom"], POLYGON_MIN_ZOOM)
        self.assertContains(response, f"polygonMinZoom: {POLYGON_MIN_ZOOM},")

    def test_page_configures_the_initial_user_radius(self) -> None:
        self.assertContains(self.client.get("/"), "userRadiusKm: 100,")

    def test_page_does_not_suppress_referer_for_osm_tiles(self) -> None:
        # OSM's tile usage policy requires browsers to send a valid Referer; Django's default
        # "same-origin" policy would strip it from cross-origin tile requests (403 Access Blocked).
        response = self.client.get("/")

        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_map_script_is_served_by_staticfiles(self) -> None:
        self.assertIsNotNone(finders.find("facilities/map.js"))


def _tile_for(lon: float, lat: float, z: int) -> tuple[int, int]:
    """x, y of the web-mercator (XYZ) tile containing lon/lat at zoom z."""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _protobuf_fields(buf: bytes):
    """Yield (field_number, value) for each top-level field of a protobuf message. Varints come
    back as ints, length-delimited fields as bytes."""
    pos = 0
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            value, pos = buf[pos : pos + length], pos + length
        else:
            raise ValueError(f"unexpected protobuf wire type {wire}")
        yield field, value


def decode_tile(tile: bytes) -> dict[str, list[int | None]]:
    """Minimal Mapbox Vector Tile reader: {layer name: [feature id, ...]} — enough to assert which
    layers a tile has and which facilities are in them, without a decoding dependency."""
    layers: dict[str, list[int | None]] = {}
    for field, layer in _protobuf_fields(tile):
        if field != 3:  # Tile.layers
            continue
        name, ids = "", []
        for layer_field, value in _protobuf_fields(layer):
            if layer_field == 1:  # Layer.name
                name = value.decode()
            elif layer_field == 2:  # Layer.features
                feature_id = next((v for f, v in _protobuf_fields(value) if f == 1), None)
                ids.append(feature_id)
        layers[name] = ids
    return layers


class TileEndpointTests(TestCase):
    """/tiles/{z}/{x}/{y}.mvt, asserted by decoding the tile with the small reader above."""

    LON, LAT = 10.0, 45.0

    @classmethod
    def _make_facility(cls, case_id: int, lon: float, lat: float, capacity_mw: float = 12.5):
        d = 0.01
        polygon = Polygon(
            (
                (lon - d, lat - d),
                (lon - d, lat + d),
                (lon + d, lat + d),
                (lon + d, lat - d),
                (lon - d, lat - d),
            )
        )
        return SolarFacility.objects.create(
            case_id=case_id,
            name=f"Tile Test Farm {case_id}",
            state="CA",
            capacity_mw=capacity_mw,
            install_year=2020,
            geom=MultiPolygon(polygon),
            centroid=Point(lon, lat),
        )

    @classmethod
    def setUpTestData(cls) -> None:
        cls.facility = cls._make_facility(1, cls.LON, cls.LAT)

    def _get_tile(self, z: int, x: int, y: int, **extra):
        return self.client.get(f"/tiles/{z}/{x}/{y}.mvt", **extra)

    def _get_facility_tile(self, z: int, **extra):
        x, y = _tile_for(self.LON, self.LAT, z)
        return self._get_tile(z, x, y, **extra)

    def test_world_tile_has_only_the_points_layer(self) -> None:
        response = self._get_tile(0, 0, 0)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], MVT_CONTENT_TYPE)
        self.assertEqual(decode_tile(response.content), {"points": [self.facility.id]})
        # Dots carry only the feature id: no names or other properties.
        self.assertNotIn(b"Tile Test Farm", response.content)

    def test_layers_are_disjoint_and_switch_at_polygon_min_zoom(self) -> None:
        below = decode_tile(self._get_facility_tile(POLYGON_MIN_ZOOM - 1).content)
        at = decode_tile(self._get_facility_tile(POLYGON_MIN_ZOOM).content)
        high = decode_tile(self._get_facility_tile(14).content)

        self.assertEqual(below, {"points": [self.facility.id]})
        # From the threshold up: polygons only, each facility sent once (not also as a dot).
        self.assertEqual(at, {"polygons": [self.facility.id]})
        self.assertEqual(high, {"polygons": [self.facility.id]})

    def test_polygon_features_carry_the_facility_details(self) -> None:
        response = self._get_facility_tile(POLYGON_MIN_ZOOM)

        self.assertIn(b"Tile Test Farm 1", response.content)
        self.assertIn(b"capacity_mw", response.content)

    def test_points_are_thinned_to_one_per_pixel_cell_keeping_the_largest(self) -> None:
        # ~110 m from the first facility: the same ~1 px cell at zoom 0, so only one dot survives —
        # the bigger facility. A third, far away, keeps its own dot.
        near_but_bigger = self._make_facility(2, self.LON + 0.001, self.LAT, capacity_mw=80.0)
        far_away = self._make_facility(3, -100.0, 40.0)

        layers = decode_tile(self._get_tile(0, 0, 0).content)

        self.assertCountEqual(layers["points"], [near_but_bigger.id, far_away.id])

    def test_polygons_are_not_thinned(self) -> None:
        neighbour = self._make_facility(2, self.LON + 0.001, self.LAT, capacity_mw=80.0)

        layers = decode_tile(self._get_facility_tile(14).content)

        self.assertCountEqual(layers["polygons"], [self.facility.id, neighbour.id])

    def test_valid_tile_without_facilities_returns_204(self) -> None:
        x, y = _tile_for(0.0, 0.0, 12)  # open ocean, nowhere near the test facility

        response = self._get_tile(12, x, y)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")

    def test_invalid_tile_coordinates_return_404(self) -> None:
        for z, x, y in [(MAX_ZOOM + 1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 2, 0), (1, 0, 2)]:
            with self.subTest(z=z, x=x, y=y):
                self.assertEqual(self._get_tile(z, x, y).status_code, 404)

    def test_only_get_is_allowed(self) -> None:
        self.assertEqual(self.client.post("/tiles/0/0/0.mvt").status_code, 405)

    def test_tiles_are_publicly_cacheable(self) -> None:
        for response in (self._get_tile(0, 0, 0), self._get_tile(12, *_tile_for(0.0, 0.0, 12))):
            with self.subTest(status=response.status_code):
                self.assertIn("public", response["Cache-Control"])
                self.assertIn("max-age=3600", response["Cache-Control"])

    def test_gzip_is_applied_when_the_client_accepts_it(self) -> None:
        # GZipMiddleware only compresses bodies over ~200 bytes; the API list is well over that.
        response = self.client.get("/api/facilities/", headers={"accept-encoding": "gzip"})

        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", response["Vary"])

    def test_is_valid_tile(self) -> None:
        self.assertTrue(is_valid_tile(0, 0, 0))
        self.assertTrue(is_valid_tile(MAX_ZOOM, 2**MAX_ZOOM - 1, 0))
        self.assertFalse(is_valid_tile(-1, 0, 0))
        self.assertFalse(is_valid_tile(MAX_ZOOM + 1, 0, 0))
        self.assertFalse(is_valid_tile(3, 8, 0))
        self.assertFalse(is_valid_tile(3, 0, -1))
