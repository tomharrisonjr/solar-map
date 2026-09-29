import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import TestCase

from facilities.models import SolarFacility


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

    def test_list_returns_unpaginated_feature_collection(self) -> None:
        response = self.client.get("/api/facilities/")

        body = response.json()
        self.assertEqual(body["type"], "FeatureCollection")
        self.assertEqual(len(body["features"]), 3)


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


class MapViewTests(TestCase):
    def test_root_renders_map_page(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "facilities/map.html")
        self.assertContains(response, 'id="map"')
        self.assertContains(response, "/static/facilities/map.js")

    def test_page_does_not_suppress_referer_for_osm_tiles(self) -> None:
        # OSM's tile usage policy requires browsers to send a valid Referer; Django's default
        # "same-origin" policy would strip it from cross-origin tile requests (403 Access Blocked).
        response = self.client.get("/")

        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_map_script_is_served_by_staticfiles(self) -> None:
        self.assertIsNotNone(finders.find("facilities/map.js"))
