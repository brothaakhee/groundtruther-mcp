#!/usr/bin/env bash
set -euo pipefail

# Publish groundtruther-mcp to PyPI using Docker (no host pip needed)
# Usage: ./publish.sh
# Requires: PYPI_TOKEN env var or ../.env file with PYPI_TOKEN=...

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load PYPI_TOKEN from ../.env if not already set
if [ -z "${PYPI_TOKEN:-}" ]; then
  ENV_FILE="$SCRIPT_DIR/../.env"
  if [ -f "$ENV_FILE" ]; then
    PYPI_TOKEN=$(grep '^PYPI_TOKEN=' "$ENV_FILE" | cut -d'=' -f2-)
  fi
fi

if [ -z "${PYPI_TOKEN:-}" ]; then
  echo "Error: PYPI_TOKEN not set. Export it or add to ../.env"
  exit 1
fi

echo "Building and publishing groundtruther-mcp..."

# Clean old dist
rm -rf "$SCRIPT_DIR/dist"

docker run --rm \
  -v "$SCRIPT_DIR":/app \
  -w /app \
  -e PYPI_TOKEN="$PYPI_TOKEN" \
  python:3.12-slim bash -c "
    pip install -q build twine &&
    python -m build &&
    twine upload dist/* --username __token__ --password \$PYPI_TOKEN
  "

echo "Published successfully."
