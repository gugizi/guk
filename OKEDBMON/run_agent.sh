#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run ./run_collector.sh first so the Python environment is created." >&2
  exit 1
fi
echo "This agent collects the single target in config/agent.json."
exec .venv/bin/python -m agent
