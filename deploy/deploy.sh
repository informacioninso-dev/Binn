#!/bin/bash

# Deployment script for Kore ERP
# Run this script on the server after initial setup

set -e

echo "🚀 Starting deployment..."

# Pull latest changes
echo "📥 Pulling latest changes from GitHub..."
git pull origin main

# Install/update dependencies
echo "📦 Installing dependencies..."
poetry install --no-dev

# Collect static files
echo "📁 Collecting static files..."
poetry run python manage.py collectstatic --noinput

# Run migrations
echo "🗄️ Running database migrations..."
poetry run python manage.py migrate

# Restart Gunicorn
echo "🔄 Restarting Gunicorn..."
sudo systemctl restart gunicorn

# Restart Nginx
echo "🔄 Restarting Nginx..."
sudo systemctl restart nginx

echo "✅ Deployment completed successfully!"
