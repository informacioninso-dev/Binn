"""
Django settings for Binn.
"""

from pathlib import Path
import importlib.util
import os
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

from config.env import (
    DEFAULT_DEV_SECRET,
    parse_admin_identities,
    resolve_allowed_hosts,
    resolve_csrf_trusted_origins,
    resolve_tenant_base_domain,
    validate_runtime_configuration,
)

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


load_dotenv(ENV_FILE, override=False)

SECRET_KEY = (os.getenv("SECRET_KEY", DEFAULT_DEV_SECRET) or DEFAULT_DEV_SECRET).strip()
# Si no existe .env ni una variable DEBUG explicita, asumimos perfil local seguro.
DEBUG = _env_bool("DEBUG", default=not ENV_FILE.exists())
ALLOWED_HOSTS = resolve_allowed_hosts(debug=DEBUG, env_value=os.getenv("ALLOWED_HOSTS"))
TENANT_BASE_DOMAIN = resolve_tenant_base_domain(debug=DEBUG, env_value=os.getenv("TENANT_BASE_DOMAIN"))
CSRF_TRUSTED_ORIGINS = resolve_csrf_trusted_origins(debug=DEBUG, env_value=os.getenv("CSRF_TRUSTED_ORIGINS"))

validate_runtime_configuration(
    debug=DEBUG,
    secret_key=SECRET_KEY,
    allowed_hosts=ALLOWED_HOSTS,
    csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,
    tenant_base_domain=TENANT_BASE_DOMAIN,
)

CHANNELS_AVAILABLE = importlib.util.find_spec("channels") is not None
CHANNELS_REDIS_AVAILABLE = importlib.util.find_spec("channels_redis") is not None
DAPHNE_AVAILABLE = importlib.util.find_spec("daphne") is not None
# Keep Daphne available by default outside DEBUG for the realtime development
# path; local environments can still opt out with USE_DAPHNE_RUNSERVER=false.
USE_DAPHNE_RUNSERVER = _env_bool("USE_DAPHNE_RUNSERVER", default=not DEBUG)
CELERY_AVAILABLE = importlib.util.find_spec("celery") is not None

REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_URL = os.getenv("CACHE_URL", REDIS_URL).strip()
ENABLE_REALTIME = _env_bool("ENABLE_REALTIME", default=CHANNELS_AVAILABLE)
REQUIRE_REDIS_FOR_REALTIME = _env_bool("REQUIRE_REDIS_FOR_REALTIME", default=not DEBUG)
ENABLE_BACKGROUND_JOBS = _env_bool("ENABLE_BACKGROUND_JOBS", default=False)
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "8"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900"))
LOGIN_RATE_LIMIT_LOCKOUT_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_LOCKOUT_SECONDS", "1800"))

SHARED_APPS = [
    *(
        ["daphne", "channels", "django_tenants"]
        if CHANNELS_AVAILABLE and DAPHNE_AVAILABLE and USE_DAPHNE_RUNSERVER
        else ["channels", "django_tenants"]
        if CHANNELS_AVAILABLE
        else ["django_tenants"]
    ),
    "identity",
    "tenants",
    "governance",
    "access",
    "consolidation",
    "core",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

TENANT_APPS = [
    "core",
    # Internal app package. Public URLs still live under /crm/.
    "binncrm",
    "collab",
]

INSTALLED_APPS = SHARED_APPS + [app for app in TENANT_APPS if app not in SHARED_APPS]

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tenants.middleware.LocalTenantPreviewMiddleware",
    "tenants.middleware.RequestContextMiddleware",
    "access.middleware.ActiveAccessContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "tenants.middleware.TenantAccessMiddleware",
    "identity.middleware.GlobalSessionMiddleware",
    "identity.middleware.PasswordRotationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

PUBLIC_SCHEMA_NAME = "public"
PUBLIC_SCHEMA_URLCONF = "config.public_urls"
TENANT_MODEL = "tenants.Client"
TENANT_DOMAIN_MODEL = "tenants.Domain"
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)
# Reapply PostgreSQL search_path only when the active tenant changes. This is
# safe because django-tenants still switches it for every new tenant request.
TENANT_LIMIT_SET_CALLS = True

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.collab_badge",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

_db_engine = os.getenv("DB_ENGINE", "postgresql")
if _db_engine != "postgresql":
    raise ImproperlyConfigured("DB_ENGINE debe ser postgresql para multitenancy por schemas.")
# Reconnecting to PostgreSQL on every page makes tenant navigation feel slow.
# django-tenants resets the active schema per request, so persistent connections
# remain safe while avoiding that connection handshake.
DB_CONN_MAX_AGE = int(os.getenv("DB_CONN_MAX_AGE", "60"))
DB_CONN_HEALTH_CHECKS = _env_bool("DB_CONN_HEALTH_CHECKS", default=not DEBUG)
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.getenv("DB_NAME", "Binn"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": DB_CONN_MAX_AGE,
        "CONN_HEALTH_CHECKS": DB_CONN_HEALTH_CHECKS,
    }
}
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "binn-local-cache",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "tenants.auth_backends.TenantAwareBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_USER_MODEL = "identity.User"

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_TZ = True

STATIC_URL = os.getenv("STATIC_URL", "/static/").strip() or "/static/"
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", str(BASE_DIR / "staticfiles"))).resolve()
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]

MEDIA_URL = os.getenv("MEDIA_URL", "/media/").strip() or "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "media"))).resolve()

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN") or None

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_DOMAIN = os.getenv("CSRF_COOKIE_DOMAIN") or None

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
).strip()
EMAIL_HOST = os.getenv("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=not DEBUG)
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", f"no-reply@{TENANT_BASE_DOMAIN or 'localhost'}").strip()
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL).strip()
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "[Binn] ").strip()
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT", str(60 * 60 * 24)))
ADMINS = parse_admin_identities(os.getenv("DJANGO_ADMINS"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO").strip().upper() or ("DEBUG" if DEBUG else "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "text" if DEBUG else "json").strip().lower() or ("text" if DEBUG else "json")
LOG_TO_STDOUT = _env_bool("LOG_TO_STDOUT", default=True)
LOG_FILE_ENABLED = _env_bool("LOG_FILE_ENABLED", default=not DEBUG)
_log_file_path = (os.getenv("LOG_FILE_PATH", "") or "").strip()
LOG_FILE_PATH = Path(_log_file_path or str(BASE_DIR / "logs" / "binn.log")).resolve()
LOG_FILE_MAX_BYTES = int(os.getenv("LOG_FILE_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_FILE_BACKUP_COUNT = int(os.getenv("LOG_FILE_BACKUP_COUNT", "5"))
if LOG_FILE_ENABLED:
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

if not DEBUG:
    ENABLE_SSL = _env_bool("ENABLE_SSL", default=False)
    SESSION_COOKIE_SECURE = ENABLE_SSL
    CSRF_COOKIE_SECURE = ENABLE_SSL
    SECURE_SSL_REDIRECT = ENABLE_SSL
    if ENABLE_SSL:
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

_logging_formatters = {
    "verbose": {
        "format": "{levelname} {asctime} request={request_id} tenant={tenant_schema} actor={actor_id} {module} {message}",
        "style": "{",
    },
    "json": {
        "()": "core.logging.JsonFormatter",
    },
}

_logging_handlers = {}
_active_handlers: list[str] = []
_default_formatter = "json" if LOG_FORMAT == "json" else "verbose"

if LOG_TO_STDOUT:
    _logging_handlers["console"] = {
        "class": "logging.StreamHandler",
        "formatter": _default_formatter,
        "filters": ["request_context"],
    }
    _active_handlers.append("console")

if LOG_FILE_ENABLED:
    _logging_handlers["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(LOG_FILE_PATH),
        "maxBytes": LOG_FILE_MAX_BYTES,
        "backupCount": LOG_FILE_BACKUP_COUNT,
        "formatter": _default_formatter,
        "filters": ["request_context"],
    }
    _active_handlers.append("file")

if not DEBUG and ADMINS:
    _logging_handlers["mail_admins"] = {
        "class": "django.utils.log.AdminEmailHandler",
        "level": "ERROR",
        "include_html": False,
        "filters": ["require_debug_false", "request_context"],
    }
    _active_handlers.append("mail_admins")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "tenants.logging.RequestContextFilter",
        },
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
    },
    "formatters": _logging_formatters,
    "handlers": _logging_handlers,
    "root": {
        "handlers": _active_handlers,
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": _active_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": _active_handlers,
            "level": "ERROR",
            "propagate": False,
        },
        "tenants": {
            "handlers": _active_handlers,
            "level": "INFO",
            "propagate": False,
        },
    },
}

if CHANNELS_AVAILABLE:
    if REDIS_URL and CHANNELS_REDIS_AVAILABLE:
        CHANNEL_LAYERS = {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {"hosts": [REDIS_URL]},
            }
        }
    else:
        CHANNEL_LAYERS = {
            "default": {
                "BACKEND": "channels.layers.InMemoryChannelLayer",
            }
        }

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL).strip()
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL).strip()
CELERY_TASK_ALWAYS_EAGER = _env_bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG and not ENABLE_BACKGROUND_JOBS)
CELERY_TASK_EAGER_PROPAGATES = _env_bool("CELERY_TASK_EAGER_PROPAGATES", default=DEBUG)
CELERY_TASK_DEFAULT_QUEUE = os.getenv("CELERY_TASK_DEFAULT_QUEUE", "binn-default").strip() or "binn-default"
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "300"))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "240"))
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
