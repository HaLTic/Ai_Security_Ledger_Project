@echo off
rem Start the Ledger Agent dashboard in this window (Windows).
rem Opens the dashboard in your browser. Closing this window or pressing Ctrl+C stops the dashboard and any agents it started.
rem Usage: run_dashboard.bat            (default port 8765)
rem        run_dashboard.bat --port 8770
cd /d "%~dp0"

set "PY=python"
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

%PY% dashboard.py --state-dir .state --open %*
