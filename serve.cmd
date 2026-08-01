@echo off
REM Starts the API server. See analyst.cmd for why this is a .cmd and not .ps1
REM (this machine's home path contains a backtick, PowerShell's escape char).
REM
REM   http://127.0.0.1:8000/api/health
REM   http://127.0.0.1:8000/docs      interactive API reference
REM
REM Ctrl+C to stop. --reload picks up backend edits without a restart.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no virtualenv at "%~dp0.venv"
    echo Create it with:  python -m venv .venv
    exit /b 1
)

echo Starting API on http://127.0.0.1:8000
echo   health   http://127.0.0.1:8000/api/health
echo   coverage http://127.0.0.1:8000/api/coverage
echo   docs     http://127.0.0.1:8000/docs
echo.

".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload %*
