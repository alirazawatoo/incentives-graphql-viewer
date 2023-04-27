"""Django settings. Everything deployment-specific comes from environment variables."""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name, default=False):
    return os.getenv(name, "true" if default else "false").strip().lower() in TRUE_VALUES


def _env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _env_number(name, default, cast, minimum):
    raw = os.getenv(name, str(default))
    try:
        value = cast(raw)
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be a number, got {raw!r}") from None
    if not value >= minimum:  # also rejects NaN
        raise ImproperlyConfigured(f"{name} must be at least {minimum}")
    return value


DEBUG = _env_flag("DJANGO_DEBUG")
# Debug mode may run with a throwaway key so a fresh checkout starts; anything
# else must be given a real one.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or (secrets.token_urlsafe(48) if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY, or set DJANGO_DEBUG=true for local development")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
if "*" in ALLOWED_HOSTS and not DEBUG:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS='*' is only accepted with DJANGO_DEBUG=true")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# HTTPS hardening applies outside debug mode. Redirects and HSTS are opt-in
# because they depend on how TLS is terminated in front of the app.
if not DEBUG:
    SESSION_COOKIE_SECURE = _env_flag("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECURE_SSL_REDIRECT = _env_flag("DJANGO_SECURE_SSL_REDIRECT")
    SECURE_HSTS_SECONDS = _env_number("DJANGO_SECURE_HSTS_SECONDS", 0, int, 0)
    if _env_flag("DJANGO_BEHIND_TLS_PROXY"):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# GraphQL incentives API configuration.
GRAPHQL_API_URL = os.getenv("GRAPHQL_API_URL", "https://api.taomarketcap.com/graphql")
GRAPHQL_SUBNET_UID = _env_number("GRAPHQL_SUBNET_UID", 18, int, 0)
GRAPHQL_REQUEST_TIMEOUT = _env_number("GRAPHQL_REQUEST_TIMEOUT", 10, float, 0.5)
GRAPHQL_CACHE_SECONDS = _env_number("GRAPHQL_CACHE_SECONDS", 300, int, 0)
GRAPHQL_MAX_RESPONSE_BYTES = _env_number("GRAPHQL_MAX_RESPONSE_BYTES", 5_000_000, int, 1024)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "incentive-charts",
    }
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "incentives",
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

ROOT_URLCONF = "incentive_site.urls"

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

WSGI_APPLICATION = "incentive_site.wsgi.application"

# SQLite only backs Django's admin/auth/session tables; the charts never
# touch the database.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("DJANGO_SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
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
# STATICFILES_STORAGE was deprecated in Django 4.2 and is ignored from 5.1.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"incentives": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")}},
}
