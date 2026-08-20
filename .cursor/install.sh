#!/usr/bin/env bash
# Idempotent dependency setup for the guk Google Drive backup CLI.
# Creates a project virtualenv and installs the package (with its runtime
# dependencies) in editable mode when the project sources are present.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR=".venv"

python3 -m venv "$VENV_DIR"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

if [ -f pyproject.toml ]; then
  # Editable install pulls in the runtime dependencies declared in
  # pyproject.toml (google-api-python-client, google-auth*, PyYAML).
  python -m pip install -e .
  echo "Installed guk-drive-backup (editable) into $VENV_DIR."
else
  echo "No pyproject.toml found on this revision; created $VENV_DIR with base Python tooling only."
fi
