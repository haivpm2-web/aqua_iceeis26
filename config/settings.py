"""Settings for the ICEEIS aquaculture research server."""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "SECRET_KEY", "django-insecure-local-development-key-change-before-production"
)
DEBUG = os.environ.get("DEBUG", "false").lower() in {"1", "true", "yes", "on"}
if not DEBUG and (
    not os.environ.get("SECRET_KEY")
    or SECRET_KEY.startswith("django-insecure")
    or len(SECRET_KEY) < 50
):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Production requires a random SECRET_KEY of at least 50 characters; set DEBUG=true for local development."
    )
if any(
    os.environ.get(key)
    for key in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_NAME",
        "RAILWAY_ENVIRONMENT_ID",
        "RAILWAY_SERVICE_ID",
    )
) and (
    DEBUG
    or not os.environ.get("DATABASE_URL", "").startswith(
        ("postgres://", "postgresql://")
    )
):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Railway requires DEBUG=false and a PostgreSQL DATABASE_URL."
    )
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(
        ","
    )
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "monitoring",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
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
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = (
    os.environ.get("SECURE_SSL_REDIRECT", str(not DEBUG)).lower() == "true"
)
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_REDIRECT_EXEMPT = [r"^health/$"]
INGEST_API_TOKEN = os.environ.get("INGEST_API_TOKEN", "")
SOFTWARE_VERSION = os.environ.get(
    "SOFTWARE_VERSION", os.environ.get("RAILWAY_GIT_COMMIT_SHA", "development")
)
MAX_BATCH_SIZE = 5000
MAX_IMPORT_ROWS = 20000
ANALYSIS_MAX_SAMPLES = int(os.environ.get("ANALYSIS_MAX_SAMPLES", "200000"))
SENSOR_OFFLINE_SECONDS = int(os.environ.get("SENSOR_OFFLINE_SECONDS", "30"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
MAX_SAMPLE_FUTURE_SECONDS = int(os.environ.get("MAX_SAMPLE_FUTURE_SECONDS", "300"))
