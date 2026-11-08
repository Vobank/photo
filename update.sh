#!/usr/bin/env bash
# Updates Photo: pulls the latest code (git checkouts only), then re-runs the installer.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$ROOT/.git" ]]; then
    if command -v git >/dev/null 2>&1; then
        git -C "$ROOT" pull --ff-only || {
            echo "Could not fast-forward (local changes?). Resolve with git, then retry." >&2
            exit 1
        }
    else
        echo "git is not installed; skipping code update."
    fi
else
    echo "Not a git checkout: download the latest release from GitHub to update the code."
fi
exec "$ROOT/install.sh" "$@"
