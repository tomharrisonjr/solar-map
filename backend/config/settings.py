"""
Django settings for the solar_map project.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    """A comma-separated env var as a list; whitespace is trimmed and empty items dropped."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_SECRET_KEY = "change-me-in-real-envs"

SECRET_KEY: str = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
DEBUG: bool = env_bool("DEBUG")
ALLOWED_HOSTS: list[str] = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Full origins incl. scheme, e.g. https://solar-map.example.com — needed for POSTs (the admin
# login) once the site is served over HTTPS.
CSRF_TRUSTED_ORIGINS: list[str] = env_list("CSRF_TRUSTED_ORIGINS")

if not DEBUG and SECRET_KEY == DEFAULT_SECRET_KEY:
    raise ImproperlyConfigured("Set SECRET_KEY to a real secret when DEBUG is off.")

INSTALLED_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework_gis",
    "facilities",
]

MIDDLEWARE: list[str] = [
    # Compresses tiles and API JSON for clients that send Accept-Encoding: gzip. Listed first
    # so it wraps every other middleware's output. (Django masks CSRF tokens per response,
    # which is its mitigation for gzip + BREACH on the few HTML forms, e.g. the admin.)
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves collected static files from the app process (no nginx); must sit right after
    # SecurityMiddleware, per the WhiteNoise docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("DATABASE_NAME", "solar_map"),
        "USER": os.environ.get("DATABASE_USER", "solar_map"),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", "solar_map"),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT: Path = BASE_DIR / "staticfiles"

# Behind a TLS-terminating reverse proxy (Caddy in the AWS deploy): trust its
# X-Forwarded-Proto header so Django knows the request was HTTPS, and mark cookies secure.
# Off by default so local HTTP development is unaffected.
BEHIND_PROXY: bool = env_bool("BEHIND_PROXY")
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True

# Django's default ("same-origin") strips the Referer from cross-origin requests. The map's
# OpenStreetMap tile requests must carry a valid Referer or tile.openstreetmap.org blocks
# them (https://operations.osmfoundation.org/policies/tiles/). This is the browser default.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
