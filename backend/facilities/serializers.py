from __future__ import annotations

from rest_framework_gis.serializers import GeoFeatureModelSerializer

from facilities.models import SolarFacility


class SolarFacilitySerializer(GeoFeatureModelSerializer):
    class Meta:
        model: type[SolarFacility] = SolarFacility
        geo_field: str = "geom"
        fields: str = "__all__"
