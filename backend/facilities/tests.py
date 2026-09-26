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
