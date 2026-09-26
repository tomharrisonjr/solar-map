from __future__ import annotations

from django.db.models import QuerySet
from rest_framework.viewsets import ReadOnlyModelViewSet

from facilities.models import SolarFacility
from facilities.serializers import SolarFacilitySerializer


class SolarFacilityViewSet(ReadOnlyModelViewSet):
    queryset: QuerySet[SolarFacility] = SolarFacility.objects.all()
    serializer_class: type[SolarFacilitySerializer] = SolarFacilitySerializer
