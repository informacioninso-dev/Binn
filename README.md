# Onne

Repositorio base para iniciar Onne sobre Django + multitenancy por schema.

## Estado actual

- Apps activas:
  - `tenants` (schema/domain/memberships)
  - `core` (base mínima y dashboard)
  - `patients` (registro base de pacientes)
  - `appointments` (agenda de citas)
- Módulos heredados eliminados para evitar arrastrar deuda técnica.

## Arranque local

```bash
poetry install
poetry run python manage.py migrate_schemas --shared
poetry run python manage.py setup_public_tenant --domains localhost,127.0.0.1 --name "Onne Public"
poetry run python manage.py createsuperuser
poetry run python manage.py runserver
```

## Clínica inicial

```bash
poetry run python manage.py bootstrap_clinic <schema> "<nombre>" <subdominio.dominio> --admin-user <usuario> --admin-email <email> --admin-password "<password>"
```

Ejemplo:

```bash
poetry run python manage.py bootstrap_clinic clinica_a "Clínica A" clinica-a.localhost --admin-user admin --admin-email admin@onne.local --admin-password "OnneAdmin2026!"
```

## Acceso y subdominios

- El superadmin accede al portal público para gestionar tenants.
- Los usuarios normales solo pueden entrar a tenants donde tengan membresía activa.
- Para compartir sesión entre subdominios (`empresa1.dominio.com`, `empresa2.dominio.com`), define `SESSION_COOKIE_DOMAIN` y `CSRF_COOKIE_DOMAIN` como `.dominio.com`.
