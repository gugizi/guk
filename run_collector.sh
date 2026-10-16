#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
echo "OKEMON collector: http://127.0.0.1:8080/  (admin / spacemon)"
exec .venv/bin/python -m collector
