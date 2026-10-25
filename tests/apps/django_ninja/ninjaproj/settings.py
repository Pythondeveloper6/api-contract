"""Minimal settings for the django-ninja example project (tests/test_loaders_django.py)."""

SECRET_KEY = "test-only"
DEBUG = True
USE_TZ = True
ROOT_URLCONF = "ninjaproj.urls"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "api_contract.contrib.django",
]
