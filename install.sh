#!/usr/bin/env bash
# Installs or repairs Photo on Linux (x86_64, NVIDIA). Safe to re-run at any time.
#
#   ./install.sh                 opens the setup wizard in your browser
#   ./install.sh --unattended [--language de] [--models-dir DIR] [--data-dir DIR]
#                [--engine-dir DIR] [--models recommended|none|id,id] [--skip-frontend]
#                [--no-shortcut]
#
# Nothing is installed system-wide. Without a desktop session the installer runs
# unattended automatically.
set -euo pipefail

UV_VERSION="0.13.7"
UV_ASSET="uv-x86_64-unknown-linux-gnu.tar.gz"
UV_SHA256="c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83"
UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_ASSET}"
MIN_DRIVER_MAJOR=580

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/runtime"
BIN="$RUNTIME/bin"
UV="$BIN/uv"
BACKEND="$ROOT/backend"

MODELS="recommended"
UNATTENDED=0
LANGUAGE=""
MODELS_DIR=""
DATA_DIR=""
ENGINE_DIR=""
SKIP_FRONTEND=0
NO_SHORTCUT=0

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ok() { printf '  \033[32mok\033[0m  %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m   %s\n' "$1"; }
die() { printf '\n\033[31mInstallation stopped: %s\033[0m\n' "$1" >&2; exit 1; }

usage() {
    sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --models) [[ $# -ge 2 ]] || die "--models needs a value"; MODELS="$2"; shift 2 ;;
            --models=*) MODELS="${1#*=}"; shift ;;
            --unattended) UNATTENDED=1; shift ;;
            --language) [[ $# -ge 2 ]] || die "--language needs a value"; LANGUAGE="$2"; shift 2 ;;
            --models-dir) [[ $# -ge 2 ]] || die "--models-dir needs a value"; MODELS_DIR="$2"; shift 2 ;;
            --data-dir) [[ $# -ge 2 ]] || die "--data-dir needs a value"; DATA_DIR="$2"; shift 2 ;;
            --engine-dir) [[ $# -ge 2 ]] || die "--engine-dir needs a value"; ENGINE_DIR="$2"; shift 2 ;;
            --skip-frontend) SKIP_FRONTEND=1; shift ;;
            --no-shortcut) NO_SHORTCUT=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown option: $1 (see --help)" ;;
        esac
    done
}

check_system() {
    step "Checking system"
    [[ "$(uname -s)" == "Linux" ]] || die "install.sh is for Linux. On Windows use install.cmd."
    [[ "$(uname -m)" == "x86_64" ]] || die "Photo needs an x86_64 CPU (found $(uname -m))."
    ok "Linux $(uname -r)"

    command -v nvidia-smi >/dev/null 2>&1 ||
        die "No NVIDIA driver found. Install the latest driver (https://www.nvidia.com/drivers) and retry."
    local line name driver major
    line="$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -n1)" ||
        die "nvidia-smi could not talk to the GPU. Reinstall the NVIDIA driver and reboot."
    [[ -n "$line" ]] || die "nvidia-smi found no GPU."
    name="${line%%,*}"
    driver="$(echo "${line#*,}" | tr -d ' ')"
    major="${driver%%.*}"
    [[ "$major" =~ ^[0-9]+$ ]] || major=0
    if (( major < MIN_DRIVER_MAJOR )); then
        die "NVIDIA driver $driver is too old; $MIN_DRIVER_MAJOR or newer is required. Update it from https://www.nvidia.com/drivers"
    fi
    ok "$name, driver $driver"

    command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 ||
        die "curl or wget is required."
    command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required (coreutils)."
}

fetch() {  # fetch URL DEST
    local attempt
    for attempt in 1 2 3 4; do
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL --retry 2 -o "$2" "$1" && return 0
        else
            wget -q -O "$2" "$1" && return 0
        fi
        sleep $((2 ** attempt))
    done
    return 1
}

install_uv() {
    local dest="${1:-$BIN}"
    if [[ -x "$dest/uv" ]] && "$dest/uv" --version 2>/dev/null | grep -q "^uv ${UV_VERSION}\b"; then
        ok "uv $UV_VERSION"
        return
    fi
    mkdir -p "$dest"
    local tmp
    tmp="$(mktemp -d)"
    # shellcheck disable=SC2064  # expand $tmp now, not at exit
    trap "rm -rf '$tmp'; trap - RETURN" RETURN
    fetch "$UV_URL" "$tmp/$UV_ASSET" || die "could not download uv from $UV_URL"
    local actual
    actual="$(sha256sum "$tmp/$UV_ASSET" | cut -d' ' -f1)"
    [[ "$actual" == "$UV_SHA256" ]] ||
        die "uv download failed verification (got $actual). Check your connection and retry."
    tar -xzf "$tmp/$UV_ASSET" -C "$tmp"
    install -m 0755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$dest/uv"
    install -m 0755 "$tmp/uv-x86_64-unknown-linux-gnu/uvx" "$dest/uvx"
    ok "uv $UV_VERSION (verified)"
}

install_app() {
    step "Installing Photo"
    # Keep every byte uv downloads inside this folder.
    export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
    export UV_CACHE_DIR="$RUNTIME/cache"
    export UV_PYTHON_PREFERENCE="only-managed"
    export PHOTO_UV="$UV"
    unset VIRTUAL_ENV PYTHONPATH || true

    UV_PROJECT_ENVIRONMENT="$BACKEND/.venv" "$UV" sync --locked --no-dev --project "$BACKEND" ||
        die "installing the app server failed (see messages above)."
    ok "App server"

    # No desktop session (SSH, server): nothing could show the wizard.
    if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then UNATTENDED=1; fi
    if (( UNATTENDED )); then
        local args=(setup --models "$MODELS")
        if [[ -n "$LANGUAGE" ]]; then args+=(--language "$LANGUAGE"); fi
        if [[ -n "$MODELS_DIR" ]]; then args+=(--models-dir "$MODELS_DIR"); fi
        if [[ -n "$DATA_DIR" ]]; then args+=(--data-dir "$DATA_DIR"); fi
        if [[ -n "$ENGINE_DIR" ]]; then args+=(--engine-env-dir "$ENGINE_DIR"); fi
        if (( SKIP_FRONTEND )); then args+=(--skip-frontend); fi
        "$BACKEND/.venv/bin/photo" "${args[@]}" || die "setup failed (see messages above)."
    else
        step "Setup wizard"
        echo "  The wizard opens in your browser. Keep this terminal open until it finishes."
        "$BACKEND/.venv/bin/photo" setup --ui || die "setup was not completed."
    fi
}

start_photo() {
    # The wizard page waits for Photo on the same address and switches to it by itself.
    mkdir -p "$ROOT/data/logs"
    nohup "$BACKEND/.venv/bin/photo" serve > "$ROOT/data/logs/serve.out" 2>&1 &
}

create_shortcut() {
    chmod +x "$ROOT/photo.sh" "$ROOT/update.sh" 2>/dev/null || true
    if (( NO_SHORTCUT )); then return; fi
    local apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    local icon="$ROOT/frontend/public/icon.png"
    {
        echo "[Desktop Entry]"
        echo "Type=Application"
        echo "Name=Photo"
        echo "Comment=Local AI image studio"
        echo "Exec=\"$ROOT/photo.sh\""
        echo "Path=$ROOT"
        echo "Terminal=true"
        echo "Categories=Graphics;"
        if [[ -f "$icon" ]]; then echo "Icon=$icon"; fi
    } > "$apps/photo.desktop"
    ok "Application menu entry"
}

main() {
    parse_args "$@"
    echo "Photo installer - $ROOT"
    check_system
    step "Tools"
    install_uv
    install_app
    create_shortcut
    printf '\n\033[32mPhoto is ready. Start it with ./photo.sh or from the application menu.\033[0m\n'
    if (( ! UNATTENDED )); then start_photo; fi
}

# Sourcing ("source install.sh") loads the functions without installing, for tests.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
