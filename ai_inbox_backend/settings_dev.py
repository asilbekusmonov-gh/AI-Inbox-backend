"""
Development settings override — uses SQLite instead of PostgreSQL.
Only for local migration generation and testing without a Postgres server.

Usage:
    python manage.py makemigrations --settings=ai_inbox_backend.settings_dev
    python manage.py migrate --settings=ai_inbox_backend.settings_dev
    python manage.py runserver --settings=ai_inbox_backend.settings_dev
"""
from .settings import *  # noqa

# Override DB with SQLite for local dev (no PostgreSQL required)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_dev.sqlite3",
    }
}

# Disable Redis cache in local dev (use LocMemCache)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Disable Celery task routing in dev
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
