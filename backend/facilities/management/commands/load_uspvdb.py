from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import zipfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from facilities.models import SolarFacility

# Stable "latest" link to the official USPVDB GeoJSON release (a zip that contains a
# CHANGELOG, an XML metadata file, and a *versioned* .geojson such as
# uspvdb_v4_0_20260414.geojson — so we match members by suffix, never by name).
DEFAULT_SOURCE: str = "https://eerscmap.usgs.gov/uspvdb/assets/data/uspvdbGeoJSON.zip"
DATA_PAGE_URL: str = "https://eerscmap.usgs.gov/uspvdb/data/"
DOWNLOAD_TIMEOUT_SECONDS: int = 60
# USGS answers 403 to Python's default "Python-urllib/x.y" agent, so identify the app honestly.
USER_AGENT: str = "solar-map/1.0 (+https://github.com/tomharrisonjr/solar-map)"
PROGRESS_INTERVAL: int = 500

# USGS requires this citation for USPVDB use. The version in the citation changes with each
# annual release, so we print the loaded file name (which carries the version) alongside it.
CITATION: str = (
    "Fujita, K.S., Ancona, Z.H., Kramer, L.A., Straka, M., Gautreau, T.E., Garrity, C.P., "
    "Robson, D., Diffendorfer, J.E., and Hoen, B., 2023, United States Large-Scale Solar "
    "Photovoltaic Database: U.S. Geological Survey and Lawrence Berkeley National "
    "Laboratory data release."
)


class Command(BaseCommand):
    help: str = (
        "Load USPVDB solar facility data into the database. `source` is a path or "
        "http(s):// URL to either the official uspvdbGeoJSON.zip or a USPVDB GeoJSON file, "
        f"and defaults to the official release ({DEFAULT_SOURCE}). Zips are unpacked in "
        "memory and the single .geojson inside (its name is versioned) is loaded. The plain "
        "USPVDB API only returns points, not the panel-array polygons this app needs. "
        "Re-running is safe: facilities are upserted by case_id."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "source",
            type=str,
            nargs="?",
            default=DEFAULT_SOURCE,
            help="Path or URL to uspvdbGeoJSON.zip or a USPVDB GeoJSON file "
            "(default: the official USGS release)",
        )
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Do nothing (and download nothing) if any facilities are already loaded. "
            "Lets a deploy run this on every release so only a fresh database gets populated.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["if_empty"] and SolarFacility.objects.exists():
            self.stdout.write("Facilities already loaded; skipping (--if-empty).")
            return

        source: str = options["source"]
        data, loaded_name = self._load(source)
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
        self.stdout.write(
            f"\nData: {loaded_name}\nPlease cite: {CITATION}\n"
            f"(cite the version listed on {DATA_PAGE_URL})"
        )

    def _load(self, source: str) -> tuple[dict[str, Any], str]:
        """Return the parsed GeoJSON FeatureCollection and a label naming what was loaded."""
        raw = self._read_bytes(source)
        if zipfile.is_zipfile(io.BytesIO(raw)):
            return self._geojson_from_zip(raw)
        return self._parse(raw, source), source

    def _read_bytes(self, source: str) -> bytes:
        if source.startswith(("http://", "https://")):
            self.stdout.write(f"Downloading {source} ...")
            request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})  # noqa: S310
            try:
                with urllib.request.urlopen(  # noqa: S310
                    request, timeout=DOWNLOAD_TIMEOUT_SECONDS
                ) as response:
                    return response.read()
            except (urllib.error.URLError, TimeoutError) as exc:
                raise CommandError(f"Could not download {source}: {exc}") from exc
        try:
            return Path(source).read_bytes()
        except OSError as exc:
            raise CommandError(f"Could not read {source}: {exc}") from exc

    def _geojson_from_zip(self, raw: bytes) -> tuple[dict[str, Any], str]:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".geojson")]
            if len(members) != 1:
                raise CommandError(
                    f"Expected exactly one .geojson file in the zip, found {len(members)}: "
                    f"{archive.namelist()}"
                )
            return self._parse(archive.read(members[0]), members[0]), members[0]

    def _parse(self, raw: bytes, label: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise CommandError(f"{label} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or "features" not in data:
            raise CommandError(f"{label} is not a GeoJSON FeatureCollection (no 'features').")
        return data

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
