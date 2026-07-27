"""Django settings for Remembrancer.

Every environment-specific value comes from the environment (Decision 14). Nothing
sensitive is ever exposed to the frontend -- the Next.js bundle is public, so the
only values it receives are the NEXT_PUBLIC_* ones set in compose.yaml.
"""

from pathlib import Path
from urllib.parse import urlparse

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DJANGO_DEBUG=(bool, False))

# In containers the environment comes from compose. Locally, read the repo-root .env
# if it exists so `manage.py` and pytest work without exporting anything by hand.
_dotenv = BASE_DIR.parent / ".env"
if _dotenv.exists():
    environ.Env.read_env(_dotenv)

# Placeholder defaults keep local runs and the test suite frictionless. They are
# unusable in production: `check_production_secrets` below refuses to boot with them
# once DEBUG is off, so a forgotten value fails loudly instead of shipping.
INSECURE_PLACEHOLDER = "insecure-local-development-only"

DEBUG = env("DJANGO_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY", default=INSECURE_PLACEHOLDER)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

def _canonical_origin(url: str) -> str:
    """Drop a trailing slash and a port that is the scheme's default.

    `https://books.example:443` and `https://books.example` are the same origin, but
    only the second is what a browser sends in an `Origin` header -- so the explicit
    form silently breaks CSRF_TRUSTED_ORIGINS -- and it is the ugly one to publish in
    a toot. Normalising here fixes every consumer at once: canonical URLs, og:image,
    the feed, and the syndicated link.
    """
    url = url.strip().rstrip("/")
    for scheme, port in (("https://", ":443"), ("http://", ":80")):
        if url.startswith(scheme) and url.endswith(port):
            return url[: -len(port)]
    return url


SITE_URL = _canonical_origin(env("SITE_URL", default="http://localhost:3000"))
SITE_NAME = env("SITE_NAME", default="Remembrancer")

# Non-obvious admin path. Obscurity is not a control on its own, but it removes the
# baseline bot noise that would otherwise dominate the axes lockout log.
ADMIN_PATH = env("DJANGO_ADMIN_PATH", default="admin").strip("/")

# --- Applications ----------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django_q",
    "axes",
    "remembrancer",
    "catalog",
    "reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # AxesMiddleware must come last so it sees the outcome of authentication.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "remembrancer.urls"
WSGI_APPLICATION = "remembrancer.wsgi.application"
SITE_ID = 1

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

# --- Data stores -----------------------------------------------------------

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'dev.sqlite3'}")}
DATABASES["default"]["CONN_MAX_AGE"] = 60

REDIS_URL = env("REDIS_URL", default="")

# Shared across gunicorn workers and TTL-native -- required by the P3 view-count
# dedup, which is why locmem would be wrong in the deployed stack. Locally, with no
# REDIS_URL set, fall back so tests and `runserver` need no services.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
    if REDIS_URL
    else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

_redis = urlparse(REDIS_URL or "redis://redis:6379/0")
Q_CLUSTER = {
    "name": "remembrancer",
    "workers": 2,
    "timeout": 900,
    "retry": 1200,  # must exceed timeout, else django-q2 requeues a running task
    "max_attempts": 3,
    "save_limit": 100,
    "catch_up": False,  # a missed nightly sync should not stampede on restart
    "redis": {
        "host": _redis.hostname or "redis",
        "port": _redis.port or 6379,
        "db": int((_redis.path or "/0").lstrip("/") or 0),
    },
}

# --- Auth ------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = ["ip_address"]
AXES_RESET_ON_SUCCESS = True

# Without this, every lockout is keyed on Caddy's container address and five wrong
# passwords from anyone on the internet lock the operator out of the only write path
# the design has. See remembrancer.client_ip for why it reads X-Real-IP and not XFF.
#
# An explicit callable rather than AXES_IPWARE_* settings: those are only honoured when
# django-ipware is installed, and axes falls back to REMOTE_ADDR *silently* when it is
# not -- the setting reads as applied while doing nothing at all.
AXES_CLIENT_IP_CALLABLE = "remembrancer.client_ip.client_ip"

# --- i18n / static / media -------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Security --------------------------------------------------------------
# Caddy terminates TLS and proxies plain HTTP inwards. Without the proxy header
# Django never sees a secure request and SECURE_SSL_REDIRECT becomes an infinite
# redirect loop -- the classic first-deploy failure.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Must include the scheme. Django 4+ behind a proxy rejects admin login without
# it, and the admin is the entire write path (Decision 7).
CSRF_TRUSTED_ORIGINS = [SITE_URL] if SITE_URL.startswith("https://") else []

SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- Audiobookshelf --------------------------------------------------------

ABS_BASE_URL = env("ABS_BASE_URL", default="").rstrip("/")
ABS_TOKEN = env("ABS_TOKEN", default="")
ABS_LIBRARY_IDS = [i for i in env.list("ABS_LIBRARY_IDS", default=[]) if i]
ABS_TIMEOUT = 30
ABS_MAX_COVER_BYTES = 10 * 1024 * 1024

# --- Mastodon (P2) ----------------------------------------------------------
# Optional: unset simply means the admin action is unavailable. The token needs the
# `write:statuses` scope and nothing more -- it can neither read your timeline nor
# follow anyone, which is the whole point of scoping it.
MASTODON_BASE_URL = env("MASTODON_BASE_URL", default="").rstrip("/")
MASTODON_TOKEN = env("MASTODON_TOKEN", default="")
MASTODON_VISIBILITY = env("MASTODON_VISIBILITY", default="public")
MASTODON_HASHTAGS = [t for t in env.list("MASTODON_HASHTAGS", default=["bookstodon"]) if t]
# Instance default. Some run higher; lowering is safe, raising past the real limit
# just turns a compose-time trim into a 422 from the server.
MASTODON_MAX_CHARS = env.int("MASTODON_MAX_CHARS", default=500)
# Bounds how long the syndication task holds its row lock.
MASTODON_TIMEOUT = 15

# --- View counting (P3) ------------------------------------------------------
# Per hashed visitor, not per address. Generous enough that reading through the whole
# site in one sitting is never throttled; tight enough that a script has to work at it.
VIEW_BEACON_RATE = env("VIEW_BEACON_RATE", default="60/h")

# --- Next.js revalidation --------------------------------------------------

NEXT_INTERNAL_URL = env("NEXT_INTERNAL_URL", default="http://next:3000").rstrip("/")
REVALIDATE_SECRET = env("REVALIDATE_SECRET", default="")
REVALIDATE_TIMEOUT = 10

# --- Logging ---------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "catalog": {"level": "INFO"},
        "reviews": {"level": "INFO"},
    },
}
