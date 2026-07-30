#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f ./.env.production ]; then
  echo "Falta .env.production. Copia .env.production.example y completa secretos, dominios y credenciales antes del release."
  exit 1
fi

set -a
. ./.env.production
set +a

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py migrate_schemas --noinput
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py audit_identity_cutover --strict
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py check
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py check --deploy
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py collectstatic --noinput
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py platform_preflight --strict
else
  python manage.py migrate_schemas --noinput
  python manage.py audit_identity_cutover --strict
  python manage.py check
  python manage.py check --deploy
  python manage.py collectstatic --noinput
  python manage.py platform_preflight --strict
fi

if [ "${RUN_OPERATIONAL_SMOKE_TEST:-0}" = "1" ]; then
  ./deploy/smoke_test.sh --tenant-schema "${RELEASE_TENANT_SCHEMA:-public}"
fi