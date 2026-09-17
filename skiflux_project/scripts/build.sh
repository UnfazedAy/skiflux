#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip
pip install poetry
poetry config virtualenvs.create false
poetry install --no-root

python manage.py collectstatic --no-input
python manage.py migrate
