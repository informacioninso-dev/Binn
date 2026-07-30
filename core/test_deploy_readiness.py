from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

from config.env import is_strong_secret_key
from core.preflight import run_platform_preflight


def _probe_result(healthy: bool, message: str):
    return lambda **kwargs: SimpleNamespace(healthy=healthy, message=message)


class DeployReadinessTests(SimpleTestCase):
    def test_secret_key_helper_rejects_weak_or_placeholder_values(self):
        self.assertFalse(is_strong_secret_key("change-me-before-prod"))
        self.assertFalse(is_strong_secret_key("django-insecure-demo-secret-key"))
        self.assertFalse(is_strong_secret_key("aaaaabbbbbcccccdddddeeeee"))
        self.assertTrue(is_strong_secret_key("ProdSecretKey-7uD9!xP4#kLm2@qRs8%vWx1&yZa3*BcDe5^FgHi7(JkLmNo9)"))

    def test_preflight_fails_when_non_debug_secret_is_weak(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=False,
            SECRET_KEY="change-me-before-prod",
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm", "collab"],
            ALLOWED_HOSTS=["app.example.com"],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="smtp.example.com",
            DEFAULT_FROM_EMAIL="ops@example.com",
            LOG_TO_STDOUT=True,
            LOG_FILE_ENABLED=False,
            LOG_FORMAT="json",
            ADMINS=[("Ops", "ops@example.com")],
        )

        checks = run_platform_preflight(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                "cache": _probe_result(True, "Cache default responde a set/get."),
            },
        )

        secret_check = next(check for check in checks if check.code == "secret_key")
        self.assertEqual(secret_check.status, "fail")
        self.assertIn("baseline de produccion", secret_check.message)

    def test_production_env_example_captures_secure_runtime_defaults(self):
        env_example = Path(settings.BASE_DIR / ".env.production.example").read_text(encoding="utf-8")

        self.assertIn("DEBUG=False", env_example)
        self.assertIn("ENABLE_SSL=True", env_example)
        self.assertIn("EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend", env_example)
        self.assertIn("LOG_FORMAT=json", env_example)
        self.assertIn("REQUIRE_REDIS_FOR_REALTIME=True", env_example)
        self.assertIn("ENABLE_BACKGROUND_JOBS=True", env_example)
        self.assertIn("RUN_MIGRATIONS_ON_BOOT=0", env_example)
        self.assertIn("RUN_COLLECTSTATIC_ON_BOOT=0", env_example)
        self.assertIn("DB_CONN_MAX_AGE=60", env_example)
        self.assertIn("POSTGRES_SHARED_BUFFERS=96MB", env_example)
        self.assertIn("REDIS_MAXMEMORY=96mb", env_example)
        self.assertIn("CELERY_WORKER_CONCURRENCY=1", env_example)
        self.assertIn("CELERY_TASK_ALWAYS_EAGER=False", env_example)

    def test_production_compose_uses_lightweight_runtime_defaults(self):
        compose_definition = Path(settings.BASE_DIR / "docker-compose.prod.yml").read_text(encoding="utf-8")

        self.assertIn('RUN_MIGRATIONS_ON_BOOT: "0"', compose_definition)
        self.assertIn('RUN_COLLECTSTATIC_ON_BOOT: "0"', compose_definition)
        self.assertIn("MALLOC_ARENA_MAX", compose_definition)
        self.assertIn("--max-tasks-per-child=${CELERY_WORKER_MAX_TASKS_PER_CHILD:-200}", compose_definition)
        self.assertIn("shared_buffers=${POSTGRES_SHARED_BUFFERS:-96MB}", compose_definition)
        self.assertIn("--maxmemory ${REDIS_MAXMEMORY:-96mb}", compose_definition)