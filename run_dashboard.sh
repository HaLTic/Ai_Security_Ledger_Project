#!/bin/sh
# Start the Ledger Agent dashboard in this terminal (macOS / Linux).
# Opens the dashboard in your browser. Closing this terminal window or pressing Ctrl+C stops the dashboard and any agents it started.
# Usage: ./run_dashboard.sh            (default port 8765)
#        ./run_dashboard.sh --port 8770
cd "$(dirname "$0")" || exit 1

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi

# exec: the dashboard replaces this shell, so the terminal's hangup signal reaches it directly.
exec "$PY" dashboard.py --state-dir .state --open "$@"
