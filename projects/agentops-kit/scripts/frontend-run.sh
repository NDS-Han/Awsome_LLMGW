#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT/frontend"

if [ ! -d node_modules ]; then
  echo "Installing dependencies..."
  npm install
fi

exec npm run dev
