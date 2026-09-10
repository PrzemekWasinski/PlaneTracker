#!/bin/bash

#Script to open the flight history report

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT" || exit 1
source venv/bin/activate
PYTHONPATH="$PROJECT_ROOT/src" python3 -m plane_tracker.history.report
