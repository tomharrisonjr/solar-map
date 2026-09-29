from __future__ import annotations

from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from facilities.models import SolarFacility


class SolarFacilitySerializer(GeoFeatureModelSerializer):
    class Meta:
        model: type[SolarFacility] = SolarFacility
        geo_field: str = "geom"
        fields: str = "__all__"


class NearestFacilitySerializer(SolarFacilitySerializer):
    """Adds the annotated distance (metres from the query point) to each feature."""

    distance_m: serializers.SerializerMethodField = serializers.SerializerMethodField()

    def get_distance_m(self, obj: SolarFacility) -> float:
        return obj.distance.m
