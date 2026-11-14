#!/usr/bin/env sh
set -e

# Query FastAPI /health endpoint
curl -f http://127.0.0.1:8000/health || exit 1
