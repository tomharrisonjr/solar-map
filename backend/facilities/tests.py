from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase

from facilities.models import SolarFacility


class SolarFacilityModelTests(TestCase):
    def test_str_returns_name(self) -> None:
        polygon = Polygon(((-1, -1), (-1, 1), (1, 1), (1, -1), (-1, -1)))
        facility = SolarFacility.objects.create(
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
        for name, lon in [("Far", 2.0), ("Near", 0.0), ("Mid", 1.0)]:
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
