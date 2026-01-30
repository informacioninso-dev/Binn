# Instalación y configuración

## Requisitos

- Python 3.12+
- Poetry (gestor de dependencias)
- SQLite (desarrollo) o PostgreSQL (producción)

## Instalación

```bash
git clone <url-del-repo>
cd erp-b22
poetry install
poetry shell
```

## Migraciones

```bash
# Aplicar todas las migraciones
poetry run python manage.py migrate

# Si necesitas regenerar migraciones de un módulo:
poetry run python manage.py makemigrations <app>
poetry run python manage.py migrate <app>
```

## Datos semilla

```bash
poetry run python manage.py seed_data
```

## Crear superusuario

```bash
poetry run python manage.py createsuperuser
```

## Servidor de desarrollo

```bash
poetry run python manage.py runserver
```

## Documentación local

```bash
poetry run mkdocs serve
# Acceder en http://127.0.0.1:8000
```

## Solución de problemas

### Entorno virtual con versión incorrecta de Python

```bash
poetry env info              # Ver configuración actual
poetry env remove --all      # Limpiar entornos
poetry env use python3.12    # Forzar versión
poetry install --sync        # Reinstalar
```

### Ver migraciones pendientes

```bash
poetry run python manage.py showmigrations
```

### Verificar sistema

```bash
poetry run python manage.py check
```
