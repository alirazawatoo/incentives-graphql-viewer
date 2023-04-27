import os
import secrets

# The base settings refuse to start without a signing key outside debug mode.
os.environ.setdefault("DJANGO_SECRET_KEY", secrets.token_urlsafe(48))

from .settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
