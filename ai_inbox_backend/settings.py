"""
Django settings for AI-Inbox-Backend (Social-Commerce AI Inbox)
B2B SaaS — Multi-tenant arxitektura
"""

from pathlib import Path
import os
from django.core.exceptions import ImproperlyConfigured
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # Docker env vars (DB_HOST=db) ustidan yozmaslik uchun
except ImportError:
    pass

# ─────────────────────────────────────────────
# BASE
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default=None, required: bool = False):
    """
    Environment variable o'quvchi helper.
    required=True bo'lsa va variable topilmasa — xato chiqaradi.
    """
    value = os.environ.get(key, default)
    if required and value is None:
        raise ImproperlyConfigured(
            f"Muhit o'zgaruvchisi '{key}' topilmadi. "
            f".env faylini tekshiring."
        )
    return value


# ─────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY", required=True)
DEBUG = env("DEBUG", default="False").lower() == "true"
ALLOWED_HOSTS = ["*"] if DEBUG else env("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")


# ─────────────────────────────────────────────
# INSTALLED APPS
# ─────────────────────────────────────────────
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "django_celery_beat",
    "django_celery_results",

    # Loyiha app'lari
    "apps.core",
    "apps.stores",
    "apps.products",
    "apps.customers",
    "apps.chat",
    "apps.orders",
    "apps.webhooks",
    "apps.notifications",
]


# ─────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",          # CORS — birinchi bo'lishi shart
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

X_FRAME_OPTIONS = "ALLOWALL"

ROOT_URLCONF = "ai_inbox_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "ai_inbox_backend.wsgi.application"
ASGI_APPLICATION = "ai_inbox_backend.asgi.application"


# ─────────────────────────────────────────────
# DATABASE — PostgreSQL
# ─────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", required=True),
        "USER": env("DB_USER", required=True),
        "PASSWORD": env("DB_PASSWORD", required=True),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 0,           # Docker uchun connection pooling o'chirilgan
        "OPTIONS": {
            "connect_timeout": 30,   # DB ulanish timeout (10 dan 30 ga oshirildi)
        },
    }
}


# ─────────────────────────────────────────────
# CACHE — Redis
# ─────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
    }
}


# ─────────────────────────────────────────────
# CELERY — Async Tasks
# ─────────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Tashkent"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ALWAYS_EAGER = DEBUG  # Dev rejimida 0-soniyali tezkor (instant) ijro
CELERY_TASK_TIME_LIMIT = 60 * 5          # Task max 5 daqiqa ishlaydi
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 4     # 4 daqiqada ogohlantirish

# Celery Beat (Periodic Tasks — Data Retention uchun)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Noisy Neighbor oldini olish uchun — har bir do'kon alohida navbatda
CELERY_TASK_ROUTES = {
    "apps.chat.tasks.send_broadcast_message_task": {"queue": "messages"},
    "apps.webhooks.tasks.*": {"queue": "webhooks"},
    "apps.notifications.tasks.*": {"queue": "notifications"},
}

# Retry sozlamalari
CELERY_TASK_MAX_RETRIES = 3
CELERY_TASK_DEFAULT_RETRY_DELAY = 5  # sekund

# Celery Beat jadval — har kech soat 02:00 da eski xabarlarni tozalaydi
CELERY_BEAT_SCHEDULE = {
    "cleanup-old-messages-nightly": {
        "task": "apps.webhooks.tasks.cleanup_old_messages",
        "schedule": 60 * 60 * 24,  # Har 24 soatda bir
        "options": {"queue": "maintenance"},
    },
    "refresh-expiring-instagram-tokens-daily": {
        "task": "apps.stores.tasks.refresh_expiring_instagram_tokens",
        "schedule": 60 * 60 * 24,  # Har 24 soatda bir marta
        "options": {"queue": "maintenance"},
    },
    "retry-failed-bitrix-exports": {
        "task": "apps.orders.tasks.retry_failed_bitrix_exports",
        "schedule": 60 * 30,  # Har 30 daqiqada bir marta
        "options": {"queue": "maintenance"},
    },
    "retry-failed-google-sheets-exports": {
        "task": "apps.orders.tasks.retry_failed_google_sheets_exports",
        "schedule": 60 * 30,  # Har 30 daqiqada bir marta
        "options": {"queue": "maintenance"},
    },
    "send-followup-messages": {
        "task": "apps.customers.tasks.send_followup_messages",
        "schedule": 60 * 15,  # Har 15 daqiqada bir marta
        "options": {"queue": "maintenance"},
    },
}


# ─────────────────────────────────────────────
# DJANGO REST FRAMEWORK
# ─────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # 1. JWT Authentication (do'kon egasi standart login orqali)
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # 2. Telegram initData Authentication (TWA dashboard uchun)
        "apps.core.authentication.TelegramInitDataAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10000/hour",
        "user": "10000/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Social-Commerce AI Inbox API",
    "DESCRIPTION": "Instagram & Telegram sotuvlarini AI orqali avtomatlashtirish B2B SaaS platformasi API hujjatlari",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}


# ─────────────────────────────────────────────
# JWT
# ─────────────────────────────────────────────
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────
from corsheaders.defaults import default_headers

# ⚠️ XAVFSIZLIK: CORS_ALLOW_ALL_ORIGINS=True va CORS_ALLOW_CREDENTIALS=True
# bir vaqtda ishlatilishi xavfsizlik muammosi. Shu sababli bu endi DEBUG'ga
# bog'liq: dev'da (DEBUG=True) barcha originlarga ruxsat beriladi (qulaylik
# uchun), production'da (DEBUG=False) esa faqat .env'dagi
# CORS_ALLOWED_ORIGINS ro'yxatidagi domenlarga ruxsat beriladi.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-telegram-init-data",
]

if not DEBUG:
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in env("CORS_ALLOWED_ORIGINS", default="").split(",")
        if origin.strip()
    ]


# ─────────────────────────────────────────────
# AI API KEYS
# ─────────────────────────────────────────────
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")


# ─────────────────────────────────────────────
# MAXFIY MAYDONLARNI SHIFRLASH (apps/core/fields.py)
# ─────────────────────────────────────────────
# Bazadagi bot token/CRM webhook kabi maxfiy ustunlarni shifrlash uchun
# kalit. Yaratish: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# ⚠️ Bu kalit yo'qolsa, shifrlangan ma'lumot QAYTARIB BO'LMAYDI.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", default="")

# Public URL (ngrok / cloudflare tunnel / production domain)
PUBLIC_URL = env("PUBLIC_URL", default="").rstrip("/")

if PUBLIC_URL:
    CSRF_TRUSTED_ORIGINS = [PUBLIC_URL, "https://*.ngrok-free.dev", "https://*.ngrok-free.app"]



# ─────────────────────────────────────────────
# META / INSTAGRAM
# ─────────────────────────────────────────────
# ⚠️ BUG FIX: META_APP_ID avval bu yerda umuman yo'q edi — shu sababli
# apps/stores/services.py._get_app_credentials() har doim ValueError
# ko'tarardi va Instagram ulash (OAuth) funksiyasi ishlamas edi.
META_APP_ID = env("META_APP_ID", default="")
META_APP_SECRET = env("META_APP_SECRET", default="")
META_VERIFY_TOKEN = env("META_VERIFY_TOKEN", default="")


# ─────────────────────────────────────────────
# SENTRY — Monitoring
# ─────────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")

if SENTRY_DSN and not DEBUG:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        traces_sample_rate=0.1,       # 10% request'larni kuzatadi
        send_default_pii=False,        # Shaxsiy ma'lumot Sentry'ga ketmaydi
        environment="production" if not DEBUG else "development",
    )


# ─────────────────────────────────────────────
# DATA RETENTION
# ─────────────────────────────────────────────
CHAT_MESSAGE_RETENTION_DAYS = int(env("CHAT_MESSAGE_RETENTION_DAYS", default="90"))


# ─────────────────────────────────────────────
# BROADCAST (OMMAVIY REKLAMA) LIMITLARI
# ─────────────────────────────────────────────
# ⚠️ XAVFSIZLIK: bot BARCHA do'konlar uchun BITTA umumiy Telegram bot
# orqali ishlaydi. Agar bitta do'kon ortiqcha ko'p/tez-tez broadcast
# yuborsa va mijozlar buni spam deb Telegram'ga shikoyat qilsa, Telegram
# BUTUN botni cheklashi mumkin — bu bitta beparvo do'kon tufayli BARCHA
# do'konlarning mijozlarga yeta olmay qolishiga olib keladi. Shu sabab
# har bir do'kon uchun qat'iy kunlik/haftalik limit qo'yilgan. Kerak
# bo'lsa shu ikkita raqamni bu yerda o'zgartirish kifoya — boshqa hech
# qanday kodga tegish shart emas.
BROADCAST_DAILY_LIMIT_PER_STORE = int(env("BROADCAST_DAILY_LIMIT_PER_STORE", default="1"))
BROADCAST_WEEKLY_LIMIT_PER_STORE = int(env("BROADCAST_WEEKLY_LIMIT_PER_STORE", default="3"))


# ─────────────────────────────────────────────
# PASSWORD VALIDATION
# ─────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ─────────────────────────────────────────────
# INTERNATIONALIZATION
# ─────────────────────────────────────────────
LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True


# ─────────────────────────────────────────────
# STATIC & MEDIA FILES
# ─────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ─────────────────────────────────────────────
# DEFAULT PRIMARY KEY
# ─────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO" if DEBUG else "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
