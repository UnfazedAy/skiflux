#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e
# Print commands as they run to help debug where it fails
set -x

# Make Poetry available in non-interactive SSH sessions
export PATH="$HOME/.local/bin:$PATH"

echo "🚀 Starting Skiflux Automated Deployment..."

# 1. Pull latest code from Git
echo "🔄 Pulling latest changes from Git..."
# Go up to the repository root for git commands
cd "$(dirname "$0")/.."
pwd

git fetch origin
git reset --hard origin/main

# 2. Synchronize Poetry dependencies
echo "📦 Installing new dependencies via Poetry..."
# Go back into the python project folder
cd skiflux_project
poetry install --no-root --with main

# 3. Run Database Migrations
echo "🗄️ Running database migrations..."
poetry run python manage.py migrate --noinput

# 4. Collect Static Files (highly recommended for production Django)
echo "🎨 Collecting static files..."
poetry run python manage.py collectstatic --noinput

# 5. Restart Gunicorn safely
echo "♻️ Restarting Gunicorn (skiflux.service)..."
sudo systemctl restart skiflux

echo "🐝 Restarting Celery Worker (skiflux-worker.service)..."
sudo systemctl restart skiflux-worker

echo "⏱️ Restarting Celery Beat (skiflux-beat.service)..."
sudo systemctl restart skiflux-beat

echo "✅ Deployment successful! All services updated."