#!/usr/bin/env bash

set -e

exec celery \
    -A skiflux_project \
    beat \
    --loglevel=info