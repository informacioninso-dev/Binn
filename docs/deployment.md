# Despliegue

## Requisitos para producción

- Python 3.12+
- PostgreSQL 15+
- Servidor web: Gunicorn + Nginx (recomendado)
- Gestor de procesos: systemd o supervisor

## Variables de entorno

```bash
DJANGO_SETTINGS_MODULE=config.settings
SECRET_KEY=<tu-secret-key>
DEBUG=False
ALLOWED_HOSTS=tu-dominio.com
DATABASE_URL=postgres://user:pass@host:5432/erp_b22
```

## Pasos de despliegue

```bash
# 1. Instalar dependencias
poetry install --no-dev

# 2. Migraciones
poetry run python manage.py migrate

# 3. Archivos estáticos
poetry run python manage.py collectstatic --noinput

# 4. Verificar
poetry run python manage.py check --deploy

# 5. Arrancar
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

## Base de datos

Para migrar de SQLite a PostgreSQL:

```bash
# Exportar datos
poetry run python manage.py dumpdata --natural-foreign --natural-primary -o dump.json

# Cambiar DATABASE en settings.py a PostgreSQL

# Migrar esquema
poetry run python manage.py migrate

# Importar datos
poetry run python manage.py loaddata dump.json
```

## Backups

```bash
# PostgreSQL
pg_dump -Fc erp_b22 > backup_$(date +%Y%m%d).dump

# Restaurar
pg_restore -d erp_b22 backup_20260129.dump
```
