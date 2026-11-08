#!/usr/bin/env bash
# Starts Photo and opens it in the browser.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHOTO="$ROOT/backend/.venv/bin/photo"
if [[ ! -x "$PHOTO" ]]; then
    echo "Photo is not installed yet. Run ./install.sh first." >&2
    exit 1
fi
exec "$PHOTO" serve --open "$@"
