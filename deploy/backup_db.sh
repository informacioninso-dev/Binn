#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -f ./.env.production ]; then
  set -a
  . ./.env.production
  set +a
fi

BACKUP_DIR=${BACKUP_DIR:-./backups}
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="${BACKUP_DIR}/binn-${TIMESTAMP}.dump"
mkdir -p "$BACKUP_DIR"

if command -v docker >/dev/null 2>&1; then
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db \
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" -Fc > "$BACKUP_FILE"
else
  : "${DB_HOST:?DB_HOST no definido}"
  : "${DB_NAME:?DB_NAME no definido}"
  : "${DB_USER:?DB_USER no definido}"
  PGPASSWORD="${DB_PASSWORD:-}" pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT:-5432}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    -Fc > "$BACKUP_FILE"
fi

echo "Backup generado en ${BACKUP_FILE}"
