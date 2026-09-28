from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help: str = "Load USPVDB solar facility data (GeoJSON) into the database."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("source", type=str, help="Path or URL to the USPVDB GeoJSON file")

    def handle(self, *args: Any, **options: Any) -> None:
        source: str = options["source"]
        # TODO: fetch/open `source`, parse USPVDB GeoJSON features, and bulk-create
        # SolarFacility rows with geom set from the feature polygon and centroid
        # computed via geom.centroid.
        raise NotImplementedError(f"USPVDB ingestion from {source!r} not implemented yet")
