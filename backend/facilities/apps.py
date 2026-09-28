from __future__ import annotations

from django.apps import AppConfig


class FacilitiesConfig(AppConfig):
    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "facilities"
