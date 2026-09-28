from __future__ import annotations

from django.contrib.gis.db import models


class SolarFacility(models.Model):
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

    class Meta:
        indexes = [models.Index(fields=["state"])]

    def __str__(self) -> str:
        return self.name
