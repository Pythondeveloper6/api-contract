"""Minimal settings for the DRF example project (tests/test_loaders_django.py)."""

SECRET_KEY = "test-only"
DEBUG = True
USE_TZ = True
ROOT_URLCONF = "drfproj.urls"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "orders",
    "api_contract.contrib.django",
]
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}
SPECTACULAR_SETTINGS = {"TITLE": "Orders", "VERSION": "1.0.0"}
