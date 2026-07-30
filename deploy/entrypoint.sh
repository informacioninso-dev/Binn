#!/bin/sh
set -eu

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if is_truthy "${WAIT_FOR_DB:-1}"; then
  echo "Waiting for PostgreSQL at ${DB_HOST:-db}:${DB_PORT:-5432}..."
  until nc -z "${DB_HOST:-db}" "${DB_PORT:-5432}"; do
    sleep 1
  done
fi

if is_truthy "${RUN_MIGRATIONS_ON_BOOT:-1}"; then
  python manage.py migrate_schemas --noinput
fi

if is_truthy "${RUN_COLLECTSTATIC_ON_BOOT:-1}"; then
  python manage.py collectstatic --noinput
fi

exec "$@"