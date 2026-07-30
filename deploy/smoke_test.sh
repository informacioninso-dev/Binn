#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -f ./.env.production ]; then
  set -a
  . ./.env.production
  set +a
fi

if [ -f ./.env.production ] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T web python manage.py operational_smoke_test "$@"
else
  python manage.py operational_smoke_test "$@"
fi