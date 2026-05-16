#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT"

# .env 로드
if [ -f .env ]; then
  set -a; source .env; set +a
fi

exec uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
