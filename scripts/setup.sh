#!/usr/bin/env bash
# SPHEREx Change Lens - Local Environment Setup Script
set -euo pipefail

echo "=================================================="
echo "SPHEREx Change Lens - Scaffolding Setup"
echo "=================================================="

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python 3.11+ is required but not found."
    exit 1
fi

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

echo "Using Python: $($PYTHON_CMD --version)"

# Check Node
if ! command -v node &> /dev/null; then
    echo "WARNING: Node.js (v20+) is not found. Frontend setup will be skipped."
else
    echo "Using Node.js: $(node --version)"
fi

# Ensure .env exists
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Validate environment
echo "Running architecture & boundary validator..."
$PYTHON_CMD scripts/validate_environment.py

echo "Scaffold setup completed successfully."
