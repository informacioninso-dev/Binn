#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
  echo "Uso: ./deploy/restore_db.sh <archivo.dump>"
  exit 1
fi

if [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
  echo "Setea CONFIRM_RESTORE=yes para ejecutar una restauracion destructiva."
  exit 1
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BACKUP_FILE=$1
if [ ! -f "$BACKUP_FILE" ]; then
  echo "No existe el archivo $BACKUP_FILE"
  exit 1
fi

if [ -f ./.env.production ]; then
  set -a
  . ./.env.production
  set +a
fi

if command -v docker >/dev/null 2>&1; then
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db \
    pg_restore -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists --no-owner --no-privileges < "$BACKUP_FILE"
else
  : "${DB_HOST:?DB_HOST no definido}"
  : "${DB_NAME:?DB_NAME no definido}"
  : "${DB_USER:?DB_USER no definido}"
  PGPASSWORD="${DB_PASSWORD:-}" pg_restore \
    -h "${DB_HOST}" \
    -p "${DB_PORT:-5432}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges < "$BACKUP_FILE"
fi

echo "Restore completado desde ${BACKUP_FILE}"
