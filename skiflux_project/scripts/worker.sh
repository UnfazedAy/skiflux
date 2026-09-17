#!/usr/bin/env bash

set -e

exec celery \
    -A skiflux_project \
    worker \
    --loglevel=info \
    --concurrency=4
