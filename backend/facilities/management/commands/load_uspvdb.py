from __future__ import annotations

import json
import urllib.request
from argparse import ArgumentParser
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction

from facilities.models import SolarFacility

PROGRESS_INTERVAL: int = 500


class Command(BaseCommand):
    help: str = (
        "Load USPVDB solar facility data into the database. `source` is a path or "
        "http(s):// URL to a USPVDB GeoJSON file — download `uspvdbGeoJSON.zip` from "
        "https://eerscmap.usgs.gov/uspvdb/data/ and extract it first (this command does "
        "not handle zip files, and the plain USPVDB API only returns points, not the "
        "panel-array polygons this app needs)."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("source", type=str, help="Path or URL to the USPVDB GeoJSON file")

    def handle(self, *args: Any, **options: Any) -> None:
        source: str = options["source"]
        data: dict[str, Any] = self._load(source)
        features: list[dict[str, Any]] = data["features"]

        created_count = 0
        updated_count = 0
        with transaction.atomic():
            for i, feature in enumerate(features, start=1):
                _, created = self._upsert(feature)
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                if i % PROGRESS_INTERVAL == 0:
                    self.stdout.write(f"Processed {i}/{len(features)} features...")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created_count} created, {updated_count} updated "
                f"({len(features)} total features)."
            )
        )

    def _load(self, source: str) -> dict[str, Any]:
        if source.startswith(("http://", "https://")):
            with urllib.request.urlopen(source) as response:  # noqa: S310
                return json.load(response)
        with open(source) as f:
            return json.load(f)

    def _upsert(self, feature: dict[str, Any]) -> tuple[SolarFacility, bool]:
        props: dict[str, Any] = feature["properties"]
        geom = GEOSGeometry(json.dumps(feature["geometry"]))
        if isinstance(geom, Polygon):
            geom = MultiPolygon(geom, srid=geom.srid)

        eia_id = props.get("eia_id")
        return SolarFacility.objects.update_or_create(
            case_id=props["case_id"],
            defaults={
                "name": props.get("p_name"),
                "state": props.get("p_state"),
                "capacity_mw": props.get("p_cap_ac"),
                "install_year": props.get("p_year"),
                "eia_id": str(eia_id) if eia_id is not None else None,
                "geom": geom,
                "centroid": geom.centroid,
            },
        )
