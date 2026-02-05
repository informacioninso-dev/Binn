#!/bin/bash

# Deployment script for Kore ERP
# Run this script on the server after initial setup
# Usage: sudo -u kore bash deploy/deploy.sh

set -e

APP_DIR="/var/www/kore_erp"
POETRY_BIN="$HOME/.local/bin/poetry"

# Verificar que estamos en el directorio correcto
if [ ! -f "$APP_DIR/manage.py" ]; then
    echo "ERROR: No se encuentra manage.py en $APP_DIR"
    exit 1
fi

cd "$APP_DIR"

# Verificar que Poetry existe
if ! command -v poetry &> /dev/null && [ ! -f "$POETRY_BIN" ]; then
    echo "ERROR: Poetry no encontrado. Instalar con:"
    echo "  curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

echo "Starting deployment..."

# Pull latest changes
echo "Pulling latest changes from GitHub..."
git pull origin main

# Install/update dependencies
echo "Installing dependencies..."
poetry install --no-dev

# Collect static files
echo "Collecting static files..."
poetry run python manage.py collectstatic --noinput

# Run migrations
echo "Running database migrations..."
poetry run python manage.py migrate

# Restart Gunicorn
echo "Restarting Gunicorn..."
sudo systemctl restart gunicorn

# Restart Nginx
echo "Restarting Nginx..."
sudo systemctl restart nginx

echo "Deployment completed successfully!"
echo "Verify status with:"
echo "  sudo systemctl status gunicorn"
echo "  sudo systemctl status nginx"
