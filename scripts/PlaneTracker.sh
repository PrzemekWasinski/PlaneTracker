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

# Release this app's listening port before rebuilding and starting a new server.
"$PYTHON" - "$PROJECT_DIR" "$PORT" "$@" <<'PY'
import argparse
from pathlib import Path
import sys

import psutil

project = Path(sys.argv[1]).resolve()
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--port', type=int, default=int(sys.argv[2]))
args, _ = parser.parse_known_args(sys.argv[3:])
port = args.port
if not 1 <= port <= 65535:
    sys.exit('Error: port must be between 1 and 65535.')

try:
    listeners = [c for c in psutil.net_connections(kind='tcp')
                 if c.status == psutil.CONN_LISTEN and c.laddr.port == port]
    targets = []
    for pid in {c.pid for c in listeners}:
        if pid is None:
            sys.exit(f'Error: port {port} is occupied, but its owner cannot be identified.')
        try:
            process = psutil.Process(pid)
            command = process.cmdline()
            cwd = Path(process.cwd()).resolve()
            script = project / 'scripts/run_web.py'
            is_script = any((cwd / arg).resolve() == script for arg in command[1:] if not arg.startswith('-'))
            is_module = any(command[i:i + 2] == ['-m', 'plane_tracker.web']
                            for i in range(len(command) - 1)) and cwd == project
            if not (is_script or is_module):
                sys.exit(f'Error: port {port} is used by another app (PID {pid}); it was left running.')
            targets.append(process)
        except psutil.NoSuchProcess:
            continue

    for process in targets:
        print(f'Stopping previous PlaneTracker instance (PID {process.pid}) on port {port}...', flush=True)
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(targets, timeout=5)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=3)
    if alive:
        sys.exit(f'Error: previous PlaneTracker instance did not stop; port {port} is still occupied.')
except psutil.AccessDenied:
    sys.exit(f'Error: cannot inspect or stop the process on port {port}. Stop it manually or choose another port.')
PY

# Keep accepting --rebuild for existing shortcuts; every launch now rebuilds.
if [[ "${1:-}" == "--rebuild" ]]; then
    shift
fi

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

printf '\nOpening PlaneTracker at http://127.0.0.1:%s/\n' "$PORT"
printf 'For another computer, use this Linux machine’s LAN IP instead of 127.0.0.1.\n'
printf 'Keep this terminal open. Press Ctrl+C to stop.\n\n'
exec "$PYTHON" "$PROJECT_DIR/scripts/run_web.py" --host "$HOST" --port "$PORT" --open "$@"

