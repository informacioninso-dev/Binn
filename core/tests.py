from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from config.env import (
    DEFAULT_DEV_SECRET,
    DEFAULT_LOCAL_ALLOWED_HOSTS,
    DEFAULT_LOCAL_CSRF_TRUSTED_ORIGINS,
    resolve_allowed_hosts,
    resolve_csrf_trusted_origins,
    resolve_tenant_base_domain,
    validate_runtime_configuration,
)
from access.models import TenantMembership
from core.navigation import build_command_palette_model, build_navigation_model
from core.preflight import run_platform_preflight, summarize_preflight
from core.runtime_services import RuntimeProbeResult, get_runtime_services_status
from core.views import build_dashboard_experience
from identity.forms import StrictPasswordResetForm
from tenants.defaults import PROFILE_BROKER, PROFILE_CONDOMINIO, PROFILE_GENERAL, PROFILE_MARKETING, PROFILE_RETAIL_MODA, PROFILE_SERVICIOS


def _probe_result(healthy: bool, message: str):
    return lambda **kwargs: RuntimeProbeResult(healthy=healthy, message=message)


class NavigationModelTests(SimpleTestCase):
    def _request(self, *, is_authenticated=True, is_superuser=False, tenant=None, membership=None, namespace="", url_name="dashboard"):
        return SimpleNamespace(
            user=SimpleNamespace(is_authenticated=is_authenticated, is_superuser=is_superuser),
            tenant=tenant,
            tenant_membership=membership,
            resolver_match=SimpleNamespace(namespace=namespace, url_name=url_name),
        )

    def _tenant(self, *capabilities, labels=None, profile=PROFILE_BROKER, feature_flags=None, module_order=None, role_policies=None):
        resolved_flags = feature_flags or {capability: True for capability in capabilities}
        return SimpleNamespace(
            schema_name="broker_demo",
            has_capability=lambda capability: capability in set(capabilities),
            tenant_config=SimpleNamespace(
                labels=labels or {},
                profile=profile,
                feature_flags=resolved_flags,
                module_order=module_order or [],
                role_policies=role_policies or {},
            ),
        )

    def test_public_superadmin_sees_tenants_and_holdings_sections(self):
        request = self._request(
            is_superuser=True,
            tenant=SimpleNamespace(schema_name="public"),
        )

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Tenants", "Holdings"])
        self.assertEqual([item.label for item in nav.utility_items], ["Cambiar clave"])

    def test_public_tenants_nav_stays_active_on_detail_pages(self):
        request = self._request(
            is_superuser=True,
            tenant=SimpleNamespace(schema_name="public"),
            namespace="tenants",
            url_name="detail",
        )

        nav = build_navigation_model(request)

        self.assertTrue(nav.primary_items[0].active)

    def test_public_superadmin_command_palette_includes_holdings(self):
        request = self._request(
            is_superuser=True,
            tenant=SimpleNamespace(schema_name="public"),
        )

        sections = build_command_palette_model(request)

        self.assertTrue(any(item.label == "Holdings" for section in sections for item in section.items))

    def test_superadmin_inside_tenant_gets_return_to_platform_action(self):
        tenant = self._tenant("entities")
        request = self._request(
            is_superuser=True,
            tenant=tenant,
            namespace="binncrm",
            url_name="entities",
        )

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.utility_items], ["Volver a Tenants", "Cambiar clave"])

    def test_only_selected_primary_module_is_marked_active(self):
        tenant = self._tenant(
            "entities",
            "deals",
            labels={"entity_plural": "Contactos", "deal_plural": "Oportunidades"},
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_OPERATOR,
            role_label="Operador",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="entities")

        nav = build_navigation_model(request)

        self.assertEqual(
            [(item.label, item.active) for item in nav.primary_items],
            [("Inicio", False), ("Contactos", True), ("Oportunidades", False)],
        )

    def test_tenant_operator_sees_crm_navigation_with_dynamic_labels(self):
        tenant = self._tenant(
            "entities",
            "deals",
            "activities",
            labels={
                "entity_plural": "Asegurados",
                "deal_plural": "Renovaciones",
                "activity_plural": "Seguimiento",
            },
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_OPERATOR,
            role_label="Operador",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="activities")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Inicio", "Asegurados", "Renovaciones"])
        self.assertEqual(
            [item.hint for item in nav.primary_items],
            ["Operacion de hoy", "Fichas y contexto", "Pipeline comercial"],
        )
        self.assertIsNotNone(nav.management_menu)
        self.assertEqual(nav.management_menu.label, "Operacion")
        self.assertEqual([item.label for item in nav.management_menu.items], ["Seguimiento"])
        self.assertEqual([item.hint for item in nav.management_menu.items], ["Tareas y seguimiento"])
        self.assertTrue(nav.management_menu.active)

    def test_disabled_modules_do_not_render_navigation_items(self):
        tenant = self._tenant(
            "entities",
            labels={
                "entity_plural": "Residentes",
                "deal_plural": "Recaudaciones",
                "activity_plural": "Actividades",
                "document_plural": "Documentos",
            },
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_ANALYST,
            role_label="Analista",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="entities")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Inicio", "Residentes"])
        self.assertIsNone(nav.management_menu)

    def test_navigation_respects_configured_module_order(self):
        tenant = self._tenant(
            "entities",
            "deals",
            "activities",
            "documents",
            labels={
                "entity_plural": "Asegurados",
                "deal_plural": "Renovaciones",
                "activity_plural": "Seguimiento",
                "document_plural": "Documentos",
            },
            module_order=["documents", "activities", "deals", "entities"],
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_MANAGER,
            role_label="Manager",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="documents")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Inicio", "Renovaciones", "Asegurados"])
        self.assertEqual([item.label for item in nav.management_menu.items], ["Documentos", "Seguimiento"])

    def test_navigation_hides_module_without_view_permission(self):
        tenant = self._tenant(
            "entities",
            "deals",
            role_policies={"viewer": ["dashboard.view", "entities.view"]},
            labels={"entity_plural": "Contactos", "deal_plural": "Deals"},
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_VIEWER,
            role_label="Consulta",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="entities")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Inicio", "Contactos"])

    def test_navigation_renders_proposals_and_collections_in_management_menu(self):
        tenant = self._tenant(
            "entities",
            "deals",
            "proposals",
            "collections",
            labels={
                "entity_plural": "Asegurados",
                "deal_plural": "Renovaciones",
                "proposal_plural": "Cotizaciones",
                "collection_plural": "Cobros",
            },
            module_order=["collections", "proposals", "deals", "entities"],
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_MANAGER,
            role_label="Manager",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="collections")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.management_menu.items], ["Cobros", "Cotizaciones"])

    def test_navigation_renders_reports_when_enabled(self):
        tenant = self._tenant(
            "entities",
            "reports",
            labels={"entity_plural": "Clientes"},
            module_order=["reports", "entities"],
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_ANALYST,
            role_label="Analista",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="reports")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.management_menu.items], ["Reportes"])
        self.assertTrue(nav.management_menu.active)

    def test_retail_profile_surfaces_retail_hub_before_entities(self):
        tenant = self._tenant(
            "entities",
            "deals",
            "activities",
            "reports",
            labels={"entity_plural": "Clientes", "deal_plural": "Pedidos especiales"},
            profile=PROFILE_RETAIL_MODA,
            module_order=["entities", "deals", "activities", "reports"],
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_MANAGER,
            role_label="Manager",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="retail_hub")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items[:3]], ["Inicio", "Retail", "Clientes"])
        self.assertTrue(nav.primary_items[1].active)

    def test_navigation_renders_custom_objects_when_tenant_has_them(self):
        tenant = self._tenant(
            "entities",
            labels={"entity_plural": "Clientes"},
            role_policies={"manager": ["dashboard.view", "entities.view", "objects.view"]},
        )
        tenant.tenant_config.custom_objects = [
            {"key": "entregable", "label": "Entregables", "fields": [{"key": "nombre", "label": "Nombre", "type": "text"}]}
        ]
        membership = SimpleNamespace(
            is_admin=True,
            role=TenantMembership.ROLE_MANAGER,
            role_label="Manager",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="binncrm", url_name="custom_object_catalog")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.management_menu.items], ["Objetos"])


class BrandingAssetTests(SimpleTestCase):
    def test_base_template_uses_existing_svg_favicon(self):
        base_template = Path(settings.BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")

        self.assertIn("img/logo.svg", base_template)
        self.assertTrue((settings.BASE_DIR / "static" / "img" / "logo.svg").exists())


class RuntimeConfigValidationTests(SimpleTestCase):
    def test_debug_defaults_resolve_to_local_values(self):
        self.assertEqual(resolve_allowed_hosts(debug=True, env_value=None), list(DEFAULT_LOCAL_ALLOWED_HOSTS))
        self.assertEqual(
            resolve_csrf_trusted_origins(debug=True, env_value=None),
            list(DEFAULT_LOCAL_CSRF_TRUSTED_ORIGINS),
        )
        self.assertEqual(resolve_tenant_base_domain(debug=True, env_value=None), "localhost")

    def test_production_requires_explicit_allowed_hosts(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "ALLOWED_HOSTS debe estar configurado"):
            validate_runtime_configuration(
                debug=False,
                secret_key="prod-secret",
                allowed_hosts=[],
                csrf_trusted_origins=["https://app.example.com"],
                tenant_base_domain="example.com",
            )

    def test_production_requires_explicit_csrf_trusted_origins(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "CSRF_TRUSTED_ORIGINS debe estar configurado"):
            validate_runtime_configuration(
                debug=False,
                secret_key="prod-secret",
                allowed_hosts=["app.example.com"],
                csrf_trusted_origins=[],
                tenant_base_domain="example.com",
            )

    def test_production_requires_explicit_tenant_base_domain(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "TENANT_BASE_DOMAIN debe estar configurado"):
            validate_runtime_configuration(
                debug=False,
                secret_key="prod-secret",
                allowed_hosts=["app.example.com"],
                csrf_trusted_origins=["https://app.example.com"],
                tenant_base_domain="",
            )

    def test_debug_rejects_public_domain_configuration(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DEBUG=True solo se permite con configuracion local"):
            validate_runtime_configuration(
                debug=True,
                secret_key=DEFAULT_DEV_SECRET,
                allowed_hosts=["app.example.com"],
                csrf_trusted_origins=["https://app.example.com"],
                tenant_base_domain="example.com",
            )


class PreflightTests(SimpleTestCase):
    def test_preflight_flags_default_secret_in_non_debug_as_fail(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=False,
            SECRET_KEY=DEFAULT_DEV_SECRET,
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm", "collab"],
            ALLOWED_HOSTS=["localhost"],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
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

    def test_preflight_summary_counts_warn_and_fail(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=True,
            SECRET_KEY=DEFAULT_DEV_SECRET,
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm"],
            ALLOWED_HOSTS=[],
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            CACHE_URL="",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        )

        summary = summarize_preflight(
            run_platform_preflight(
                settings_obj=fake_settings,
                probe_overrides={
                    "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                    "cache": _probe_result(True, "Cache default responde a set/get."),
                },
            )
        )

        self.assertGreaterEqual(summary["warn"], 1)
        self.assertGreaterEqual(summary["fail"], 1)

    def test_preflight_fails_when_background_jobs_are_enabled_without_celery(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=False,
            SECRET_KEY="prod-secret",
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm", "collab"],
            ALLOWED_HOSTS=["app.example.com"],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            REDIS_URL="redis://localhost:6379/0",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
            CHANNELS_AVAILABLE=True,
            CHANNELS_REDIS_AVAILABLE=True,
            ENABLE_REALTIME=True,
            REQUIRE_REDIS_FOR_REALTIME=True,
            CHANNEL_LAYERS={"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}},
            ENABLE_BACKGROUND_JOBS=True,
            CELERY_AVAILABLE=False,
            CELERY_BROKER_URL="redis://localhost:6379/1",
            CELERY_RESULT_BACKEND="redis://localhost:6379/2",
            CELERY_TASK_ALWAYS_EAGER=False,
        )

        checks = run_platform_preflight(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                "redis": _probe_result(True, "Redis responde a PING."),
                "cache": _probe_result(True, "Cache default responde a set/get."),
            },
        )
        background_check = next(check for check in checks if check.code == "background_jobs")

        self.assertEqual(background_check.status, "fail")

    def test_preflight_warns_when_realtime_uses_memory_layer(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=True,
            SECRET_KEY="dev-secret",
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm", "collab"],
            ALLOWED_HOSTS=["localhost"],
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            REDIS_URL="",
            CACHE_URL="",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
            CHANNELS_AVAILABLE=True,
            CHANNELS_REDIS_AVAILABLE=True,
            ENABLE_REALTIME=True,
            REQUIRE_REDIS_FOR_REALTIME=False,
            CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
            ENABLE_BACKGROUND_JOBS=False,
            CELERY_AVAILABLE=False,
            CELERY_BROKER_URL="",
            CELERY_RESULT_BACKEND="",
            CELERY_TASK_ALWAYS_EAGER=False,
        )

        checks = run_platform_preflight(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                "cache": _probe_result(True, "Cache default responde a set/get."),
            },
        )
        realtime_check = next(check for check in checks if check.code == "realtime_runtime")

        self.assertEqual(realtime_check.status, "warn")

    def test_preflight_fails_when_database_probe_fails(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=False,
            SECRET_KEY="prod-secret",
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm", "collab"],
            ALLOWED_HOSTS=["app.example.com"],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
        )

        checks = run_platform_preflight(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(False, "Base de datos fallo: timeout"),
                "cache": _probe_result(True, "Cache default responde a set/get."),
            },
        )
        database_check = next(check for check in checks if check.code == "database_runtime")

        self.assertEqual(database_check.status, "fail")

    def test_preflight_fails_when_production_uses_console_email_backend(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=False,
            SECRET_KEY="prod-secret",
            AUTH_USER_MODEL="identity.User",
            SHARED_APPS=["identity", "governance", "access", "consolidation", "tenants"],
            TENANT_APPS=["binncrm", "collab"],
            ALLOWED_HOSTS=["app.example.com"],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            PUBLIC_SCHEMA_URLCONF="config.public_urls",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
            DEFAULT_FROM_EMAIL="ops@example.com",
            LOG_TO_STDOUT=True,
            LOG_FILE_ENABLED=True,
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
        email_check = next(check for check in checks if check.code == "email_delivery")

        self.assertEqual(email_check.status, "fail")

    def test_preflight_warns_when_production_logs_stdout_without_json(self):
        fake_settings = SimpleNamespace(
            BASE_DIR=settings.BASE_DIR,
            DEBUG=False,
            SECRET_KEY="prod-secret",
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
            LOG_FORMAT="text",
            ADMINS=[("Ops", "ops@example.com")],
        )

        checks = run_platform_preflight(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                "cache": _probe_result(True, "Cache default responde a set/get."),
            },
        )
        observability_check = next(check for check in checks if check.code == "observability_runtime")

        self.assertEqual(observability_check.status, "warn")


class RuntimeServicesTests(SimpleTestCase):
    def test_runtime_services_report_worker_mode_when_celery_is_ready(self):
        fake_settings = SimpleNamespace(
            REDIS_URL="redis://localhost:6379/0",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
            CHANNELS_AVAILABLE=True,
            CHANNELS_REDIS_AVAILABLE=True,
            ENABLE_REALTIME=True,
            REQUIRE_REDIS_FOR_REALTIME=True,
            CHANNEL_LAYERS={"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}},
            CELERY_AVAILABLE=True,
            ENABLE_BACKGROUND_JOBS=True,
            CELERY_BROKER_URL="redis://localhost:6379/1",
            CELERY_RESULT_BACKEND="redis://localhost:6379/2",
            CELERY_TASK_ALWAYS_EAGER=False,
        )

        status = get_runtime_services_status(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                "redis": _probe_result(True, "Redis responde a PING."),
                "cache": _probe_result(True, "Cache default responde a set/get."),
                "celery_broker": _probe_result(True, "Broker de Celery acepta conexiones."),
                "celery_workers": _probe_result(True, "1 worker(s) de Celery responden al ping."),
                "celery_result_backend": _probe_result(True, "Celery result backend responde a PING."),
            },
        )

        self.assertTrue(status["database"].healthy)
        self.assertEqual(status["channels"].mode, "redis")
        self.assertEqual(status["cache"].mode, "redis")
        self.assertEqual(status["celery"].mode, "worker")
        self.assertTrue(status["redis"].healthy)

    def test_runtime_services_mark_realtime_unhealthy_when_redis_probe_fails(self):
        fake_settings = SimpleNamespace(
            REDIS_URL="redis://localhost:6379/0",
            CACHE_URL="redis://localhost:6379/9",
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
            CHANNELS_AVAILABLE=True,
            CHANNELS_REDIS_AVAILABLE=True,
            ENABLE_REALTIME=True,
            REQUIRE_REDIS_FOR_REALTIME=True,
            CHANNEL_LAYERS={"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}},
            CELERY_AVAILABLE=False,
            ENABLE_BACKGROUND_JOBS=False,
            CELERY_BROKER_URL="",
            CELERY_RESULT_BACKEND="",
            CELERY_TASK_ALWAYS_EAGER=False,
        )

        status = get_runtime_services_status(
            settings_obj=fake_settings,
            probe_overrides={
                "database": _probe_result(True, "Base de datos responde a SELECT 1."),
                "redis": _probe_result(False, "Redis fallo: timeout"),
                "cache": _probe_result(True, "Cache default responde a set/get."),
            },
        )

        self.assertFalse(status["redis"].healthy)
        self.assertFalse(status["channels"].healthy)


class DashboardExperienceTests(SimpleTestCase):
    def _tenant(self, *, profile, labels, feature_flags, module_order=None, dashboard_widgets=None):
        return SimpleNamespace(
            tenant_config=SimpleNamespace(
                profile=profile,
                labels=labels,
                feature_flags=feature_flags,
                module_order=module_order or [],
                dashboard_widgets=dashboard_widgets or [],
            )
        )

    def test_broker_dashboard_prioritizes_documents(self):
        tenant = self._tenant(
            profile=PROFILE_BROKER,
            labels={
                "entity_singular": "Asegurado",
                "entity_plural": "Asegurados",
                "deal_singular": "Renovacion",
                "deal_plural": "Renovaciones",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": True,
                "kanban": True,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {"entities": 18, "open_deals": 7, "activities_due": 3, "documents": 24},
        )

        self.assertEqual(dashboard["kicker"], "Broker de seguros")
        self.assertIn("Documentos de emision", dashboard["highlights"])
        self.assertTrue(any(card["title"] == "Documentos" for card in dashboard["summary_cards"]))
        self.assertTrue(any(action["label"] == "Registrar documento" for action in dashboard["quick_actions"]))

    def test_condominio_dashboard_uses_collection_copy(self):
        tenant = self._tenant(
            profile=PROFILE_CONDOMINIO,
            labels={
                "entity_singular": "Residente",
                "entity_plural": "Residentes",
                "deal_singular": "Cobro",
                "deal_plural": "Recaudaciones",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": False,
                "kanban": True,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {"entities": 80, "open_deals": 11, "activities_due": 6, "documents": 0},
        )

        self.assertEqual(dashboard["entity_heading"], "Residentes recientes")
        self.assertEqual(dashboard["activity_heading"], "Actividad de recaudacion")
        self.assertIn("Recaudacion diaria", dashboard["highlights"])
        self.assertTrue(dashboard["show_pipeline_panel"])

    def test_marketing_dashboard_hides_pipeline_panel_when_kanban_disabled(self):
        tenant = self._tenant(
            profile=PROFILE_MARKETING,
            labels={
                "entity_singular": "Lead",
                "entity_plural": "Leads",
                "deal_singular": "Oportunidad",
                "deal_plural": "Oportunidades",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": False,
                "kanban": False,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {"entities": 42, "open_deals": 9, "activities_due": 4, "documents": 0},
        )

        self.assertFalse(dashboard["show_pipeline_panel"])
        self.assertEqual(dashboard["summary_cards"][1]["cta"], "")

    def test_dashboard_uses_module_order_and_widget_visibility(self):
        tenant = self._tenant(
            profile=PROFILE_BROKER,
            labels={
                "entity_singular": "Asegurado",
                "entity_plural": "Asegurados",
                "deal_singular": "Renovacion",
                "deal_plural": "Renovaciones",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": True,
                "kanban": True,
            },
            module_order=["documents", "deals", "entities", "activities"],
            dashboard_widgets=["summary_cards", "pipeline_panel"],
        )

        dashboard = build_dashboard_experience(
            tenant,
            {"entities": 18, "open_deals": 7, "activities_due": 3, "documents": 24},
        )

        self.assertEqual([card["title"] for card in dashboard["summary_cards"][:3]], ["Documentos", "Renovaciones", "Asegurados"])
        self.assertEqual(dashboard["quick_actions"], [])
        self.assertEqual(dashboard["guided_steps"], [])
        self.assertTrue(dashboard["show_pipeline_panel"])
        self.assertFalse(dashboard["show_entity_panel"])

    def test_dashboard_hides_actions_when_permissions_are_read_only(self):
        tenant = self._tenant(
            profile=PROFILE_BROKER,
            labels={
                "entity_singular": "Asegurado",
                "entity_plural": "Asegurados",
                "deal_singular": "Renovacion",
                "deal_plural": "Renovaciones",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": True,
                "kanban": True,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {"entities": 18, "open_deals": 7, "activities_due": 3, "documents": 24},
            permissions={
                "entities.view": True,
                "entities.edit": False,
                "deals.view": True,
                "deals.edit": False,
                "activities.view": True,
                "activities.edit": False,
                "documents.view": True,
                "documents.edit": False,
            },
        )

        self.assertEqual(dashboard["quick_actions"], [])
        self.assertFalse(dashboard["can_create_entity"])
        self.assertFalse(dashboard["can_create_deal"])

    def test_dashboard_hides_guided_steps_when_core_data_already_exists(self):
        tenant = self._tenant(
            profile=PROFILE_GENERAL,
            labels={
                "entity_singular": "Contacto",
                "entity_plural": "Contactos",
                "deal_singular": "Oportunidad",
                "deal_plural": "Oportunidades",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": False,
                "proposals": True,
                "collections": False,
                "reports": True,
                "kanban": True,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 6,
                "open_deals": 3,
                "activities_due": 1,
                "activities_total": 5,
                "documents": 0,
                "open_proposals": 2,
                "open_collections": 0,
                "report_alerts": 1,
            },
        )

        self.assertEqual(dashboard["guided_steps"], [])

    def test_dashboard_guided_steps_only_show_missing_setup_actions(self):
        tenant = self._tenant(
            profile=PROFILE_GENERAL,
            labels={
                "entity_singular": "Contacto",
                "entity_plural": "Contactos",
                "deal_singular": "Oportunidad",
                "deal_plural": "Oportunidades",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": False,
                "proposals": True,
                "collections": False,
                "reports": True,
                "kanban": True,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 4,
                "open_deals": 0,
                "activities_due": 0,
                "activities_total": 0,
                "documents": 0,
                "open_proposals": 0,
                "open_collections": 0,
                "report_alerts": 0,
            },
        )

        self.assertEqual(
            dashboard["guided_steps"],
            [
                "Luego crea oportunidades para mover cada oportunidad.",
                "Finalmente agenda actividades para no olvidar el seguimiento.",
            ],
        )

    def test_broker_dashboard_keeps_activity_action_alongside_documents(self):
        tenant = self._tenant(
            profile=PROFILE_BROKER,
            labels={
                "entity_singular": "Asegurado",
                "entity_plural": "Asegurados",
                "deal_singular": "Renovacion",
                "deal_plural": "Renovaciones",
                "document_singular": "Documento",
                "document_plural": "Documentos",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": True,
                "kanban": True,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {"entities": 18, "open_deals": 7, "activities_due": 3, "documents": 24},
        )

        self.assertTrue(any(action["label"] == "Registrar documento" for action in dashboard["quick_actions"]))
        self.assertTrue(any(action["label"] == "Nueva actividad" for action in dashboard["quick_actions"]))

    def test_dashboard_includes_proposals_and_collections_when_enabled(self):
        tenant = self._tenant(
            profile=PROFILE_BROKER,
            labels={
                "entity_singular": "Asegurado",
                "entity_plural": "Asegurados",
                "deal_singular": "Renovacion",
                "deal_plural": "Renovaciones",
                "document_singular": "Documento",
                "document_plural": "Documentos",
                "proposal_singular": "Cotizacion",
                "proposal_plural": "Cotizaciones",
                "collection_singular": "Cobro",
                "collection_plural": "Cobros",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": True,
                "proposals": True,
                "collections": True,
                "kanban": True,
            },
            module_order=["collections", "proposals", "deals", "entities", "activities", "documents"],
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 18,
                "open_deals": 7,
                "activities_due": 3,
                "documents": 24,
                "open_proposals": 4,
                "open_collections": 6,
            },
        )

        self.assertEqual([card["title"] for card in dashboard["summary_cards"][:2]], ["Cobros", "Cotizaciones"])
        self.assertTrue(any(action["label"] == "Registrar cotizacion" for action in dashboard["quick_actions"]))

    def test_services_dashboard_surfaces_reports_module(self):
        tenant = self._tenant(
            profile=PROFILE_SERVICIOS,
            labels={
                "entity_singular": "Cliente",
                "entity_plural": "Clientes",
                "deal_singular": "Oportunidad",
                "deal_plural": "Oportunidades",
                "document_singular": "Documento",
                "document_plural": "Documentos",
                "proposal_singular": "Propuesta",
                "proposal_plural": "Propuestas",
                "collection_singular": "Cobro",
                "collection_plural": "Cobros",
            },
            feature_flags={
                "entities": True,
                "deals": True,
                "activities": True,
                "documents": True,
                "proposals": True,
                "collections": True,
                "reports": True,
                "kanban": True,
            },
            module_order=["reports", "proposals", "deals", "entities", "activities", "documents", "collections"],
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 14,
                "open_deals": 5,
                "activities_due": 2,
                "documents": 8,
                "open_proposals": 3,
                "open_collections": 4,
                "report_alerts": 6,
            },
            permissions={"reports.view": True},
        )

        self.assertEqual(dashboard["summary_cards"][0]["title"], "Radar B2B")
        self.assertTrue(any(action["label"] == "Abrir reportes" for action in dashboard["quick_actions"]))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
    SERVER_EMAIL="alerts@example.com",
    ALLOWED_HOSTS=["localhost"],
    ENABLE_SSL=False,
    DEBUG=True,
)
class OperationsCommandsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()

    def test_send_test_email_command_emits_message(self):
        stdout = StringIO()

        call_command("send_test_email", "ops@example.com", stdout=stdout)

        self.assertIn("Correo de prueba enviado", stdout.getvalue())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ops@example.com"])

    def test_operational_smoke_test_generates_password_reset_email(self):
        self.user_model.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="x",
        )
        stdout = StringIO()

        call_command(
            "operational_smoke_test",
            "--allow-unhealthy-runtime",
            "--username",
            "root",
            stdout=stdout,
        )

        self.assertIn("Password reset generado para root@example.com", stdout.getvalue())
        self.assertEqual(len(mail.outbox), 1)

    def test_operational_smoke_test_validates_tenant_domain(self):
        self.user_model.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="x",
        )
        tenant = self.user_model._meta.apps.get_model("tenants", "Client")(
            name="Public",
            schema_name="public",
            plan="shared",
        )
        tenant.auto_create_schema = False
        tenant.save()
        self.user_model._meta.apps.get_model("tenants", "Domain").objects.create(
            tenant=tenant,
            domain="app.example.com",
            is_primary=True,
        )
        stdout = StringIO()

        call_command(
            "operational_smoke_test",
            "--allow-unhealthy-runtime",
            "--username",
            "root",
            "--tenant-schema",
            "public",
            stdout=stdout,
        )

        self.assertIn("Tenant public tiene dominio primario app.example.com", stdout.getvalue())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
)
class StrictPasswordResetFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="strict-user",
            email="strict@example.com",
            password="x",
        )

    def test_strict_password_reset_form_sends_email(self):
        form = StrictPasswordResetForm({"email": self.user.email})

        self.assertTrue(form.is_valid())

        form.save(
            domain_override="localhost",
            from_email=settings.DEFAULT_FROM_EMAIL,
            use_https=False,
            subject_template_name="auth/password_reset_subject.txt",
            email_template_name="auth/password_reset_email.txt",
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_strict_password_reset_form_raises_delivery_errors(self):
        form = StrictPasswordResetForm({"email": self.user.email})

        self.assertTrue(form.is_valid())

        with patch("identity.forms.EmailMultiAlternatives.send", side_effect=RuntimeError("smtp down")):
            with self.assertRaisesMessage(RuntimeError, "smtp down"):
                form.save(
                    domain_override="localhost",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    use_https=False,
                    subject_template_name="auth/password_reset_subject.txt",
                    email_template_name="auth/password_reset_email.txt",
                )
