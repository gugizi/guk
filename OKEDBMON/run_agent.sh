#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run ./run_collector.sh first so the Python environment is created." >&2
  exit 1
fi
exec .venv/bin/python -m agent
