from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.gis.db import models

if TYPE_CHECKING:
    from django.contrib.gis.measure import Distance


class SolarFacility(models.Model):
    case_id: models.IntegerField[int] = models.IntegerField(unique=True)
    eia_id: models.CharField[str | None] = models.CharField(
        max_length=20, unique=True, null=True, blank=True
    )
    name: models.CharField[str] = models.CharField(max_length=255)
    state: models.CharField[str] = models.CharField(max_length=2)
    capacity_mw: models.FloatField[float] = models.FloatField()
    install_year: models.IntegerField[int | None] = models.IntegerField(null=True, blank=True)
    geom: models.MultiPolygonField = models.MultiPolygonField(srid=4326)
    # Denormalized on ingestion so nearest-facility queries run against points, not polygons.
    centroid: models.PointField = models.PointField(srid=4326, null=True, blank=True)

    # Not a column: set by the nearest-facility query's `.annotate(distance=...)`.
    distance: Distance

    class Meta:
        indexes = [models.Index(fields=["state"])]

    def __str__(self) -> str:
        return self.name
