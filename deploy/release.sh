#!/bin/sh
set -eu

python manage.py migrate_schemas --noinput
python manage.py check
python manage.py check --deploy
python manage.py collectstatic --noinput
python manage.py platform_preflight --strict
