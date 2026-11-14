"""Django settings for the local Caspian Transit application."""

import os
from pathlib import Path

from .runtime import load_private_settings


BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME = BASE_DIR / ".runtime"
PRIVATE = load_private_settings(RUNTIME)

SECRET_KEY = os.environ.get("CASPIAN_DJANGO_SECRET", PRIVATE["django_secret"])
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]


# Application definition

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "transit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "caspian.urls"

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

WSGI_APPLICATION = "caspian.wsgi.application"


# Database

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("CASPIAN_DB", str(RUNTIME / "caspian.sqlite3")),
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
        },
        "TEST": {
            "NAME": str(RUNTIME / "test-caspian.sqlite3"),
        },
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Internationalization

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = RUNTIME / "static-collected"


# Browser security

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Yandex validates API keys by Referer; cross-origin requests send the origin only.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


# Local demonstration and integrations

APP_VERSION = "1.5.6-django"
GATEWAY_SECRET = os.environ.get("CASPIAN_GATEWAY_SECRET", PRIVATE["gateway_secret"])
YANDEX_MAPS_API_KEY = os.environ.get(
    "YANDEX_MAPS_API_KEY",
    PRIVATE.get("yandex_maps_api_key", ""),
)
MARINETRAFFIC_API_KEY = os.environ.get("MARINETRAFFIC_API_KEY", PRIVATE.get("marinetraffic_api_key", ""))
WINDY_POINT_API_KEY = os.environ.get("WINDY_POINT_API_KEY", PRIVATE.get("windy_point_api_key", ""))
# Respect the account's contracted request interval; conservative default until configured.
try:
    MARINETRAFFIC_CACHE_SECONDS = max(
        120,
        min(86400, int(os.environ.get("MARINETRAFFIC_CACHE_SECONDS", "3600"))),
    )
except ValueError:
    MARINETRAFFIC_CACHE_SECONDS = 3600

DATA_UPLOAD_MAX_MEMORY_SIZE = 1_500_000
FILE_UPLOAD_MAX_MEMORY_SIZE = 1_250_000

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "/accounts/login"
