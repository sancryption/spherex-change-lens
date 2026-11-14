#!/usr/bin/env sh
set -e

echo "Starting SPHEREx Change Lens API Service..."

# Ensure data directories exist
mkdir -p /app/data/cached_mefs /app/data/previews /app/data/derived /app/data/synthetic

exec "$@"
