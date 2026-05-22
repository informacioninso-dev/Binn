#!/bin/sh
set -eu

if [ "${WAIT_FOR_DB:-1}" = "1" ]; then
  echo "Waiting for PostgreSQL at ${DB_HOST:-db}:${DB_PORT:-5432}..."
  until nc -z "${DB_HOST:-db}" "${DB_PORT:-5432}"; do
    sleep 1
  done
fi

python manage.py migrate_schemas --noinput
python manage.py collectstatic --noinput

exec "$@"
