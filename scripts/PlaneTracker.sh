#!/usr/bin/env bash
# Copy this file to /home/przemek/Desktop/PlaneTracker.sh.
set -Eeuo pipefail

PROJECT_DIR="/home/przemek/PlaneTracker"
GUI_DIR="$PROJECT_DIR/src/plane_tracker/gui"
PYTHON="$PROJECT_DIR/venv/bin/python"
HOST="${PLANE_TRACKER_HOST:-0.0.0.0}"
PORT="${PLANE_TRACKER_PORT:-8080}"

fail() {
    printf '\nError: %s\n' "$*" >&2
    exit 1
}

trap 'printf "\nLaunch failed at line %s. See the error above.\n" "$LINENO" >&2' ERR

[[ -d "$PROJECT_DIR" ]] || fail "Project folder not found: $PROJECT_DIR"
[[ -x "$PYTHON" ]] || fail "Python environment missing. Run: python3 -m venv '$PROJECT_DIR/venv'"
cd "$PROJECT_DIR"

if ! "$PYTHON" -c 'import yaml, psutil, requests, firebase_admin' >/dev/null 2>&1; then
    fail "Install server dependencies: '$PYTHON' -m pip install PyYAML psutil requests firebase-admin"
fi

rebuild=0
if [[ "${1:-}" == "--rebuild" ]]; then
    rebuild=1
    shift
fi
if [[ ! -f "$GUI_DIR/dist/index.html" ]]; then
    rebuild=1
elif [[ -n "$(find "$GUI_DIR" -type d \( -name node_modules -o -name dist -o -name test-results \) -prune -o -type f \( -name '*.jsx' -o -name '*.css' -o -name '*.js' -o -name '*.html' -o -name 'package*.json' \) -newer "$GUI_DIR/dist/index.html" -print -quit)" ]]; then
    rebuild=1
fi

if (( rebuild )); then
    command -v node >/dev/null 2>&1 || fail "Node.js is missing. Install with: sudo apt install nodejs npm"
    command -v npm >/dev/null 2>&1 || fail "npm is missing. Install with: sudo apt install npm"
    printf 'Building the web interface...\n'
    (
        cd "$GUI_DIR"
        # Reinstall here so copied Windows dependencies are replaced by Linux ones.
        npm ci --no-audit --no-fund
        # Invoke Node directly to avoid permission problems with the Vite shim.
        node node_modules/vite/bin/vite.js build
    )
fi

printf '\nOpening PlaneTracker at http://127.0.0.1:%s/\n' "$PORT"
printf 'For another computer, use this Linux machine’s LAN IP instead of 127.0.0.1.\n'
printf 'Keep this terminal open. Press Ctrl+C to stop.\n\n'
exec "$PYTHON" "$PROJECT_DIR/scripts/run_web.py" --host "$HOST" --port "$PORT" --open "$@"

