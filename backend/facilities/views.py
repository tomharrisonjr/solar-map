from __future__ import annotations

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from facilities.models import SolarFacility
from facilities.serializers import NearestFacilitySerializer, SolarFacilitySerializer
from facilities.tiles import MVT_CONTENT_TYPE, build_tile, is_valid_tile

DEFAULT_NEAREST_COUNT = 5
MAX_NEAREST_COUNT = 25
TILE_CACHE_SECONDS = 3600


def _parse_param(params, name: str, cast, low, high):
    raw = params.get(name)
    if raw is None:
        raise ValidationError({name: "This query parameter is required."})
    try:
        value = cast(raw)
    except ValueError:
        raise ValidationError({name: f"Must be a valid {cast.__name__}."}) from None
    if not low <= value <= high:  # also rejects NaN
        raise ValidationError({name: f"Must be between {low} and {high}."})
    return value


class MapView(TemplateView):
    """Server-rendered page hosting the MapLibre map; all data comes from /api/facilities/."""

    template_name: str = "facilities/map.html"


@require_GET
@cache_control(public=True, max_age=TILE_CACHE_SECONDS)
def tile_view(request: HttpRequest, z: int, x: int, y: int) -> HttpResponse:
    """GET /tiles/<z>/<x>/<y>.mvt — a Mapbox Vector Tile of the facilities in that tile.

    204 (no body) for a valid tile that contains no facilities; 404 for coordinates that
    aren't a real tile.
    """
    if not is_valid_tile(z, x, y):
        raise Http404("Not a valid tile coordinate.")
    content = build_tile(z, x, y)
    if not content:
        return HttpResponse(status=204)
    return HttpResponse(content, content_type=MVT_CONTENT_TYPE)


class SolarFacilityViewSet(ReadOnlyModelViewSet):
    queryset: QuerySet[SolarFacility] = SolarFacility.objects.all()
    serializer_class: type[SolarFacilitySerializer] = SolarFacilitySerializer
    # The dataset is small (~thousands of rows), so return one full FeatureCollection for
    # the map instead of paging.
    pagination_class = None

    @action(detail=False, methods=["get"])
    def nearest(self, request: Request) -> Response:
        """GET /api/facilities/nearest/?lat=..&lon=..&n=5 — closest facilities by centroid."""
        lat = _parse_param(request.query_params, "lat", float, -90.0, 90.0)
        lon = _parse_param(request.query_params, "lon", float, -180.0, 180.0)
        if "n" in request.query_params:
            n = _parse_param(request.query_params, "n", int, 1, MAX_NEAREST_COUNT)
        else:
            n = DEFAULT_NEAREST_COUNT

        point = Point(lon, lat, srid=4326)
        facilities = (
            SolarFacility.objects.filter(centroid__isnull=False)
            .annotate(distance=Distance("centroid", point))
            .order_by("distance")[:n]
        )
        return Response(NearestFacilitySerializer(facilities, many=True).data)
