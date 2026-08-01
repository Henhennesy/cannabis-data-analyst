@echo off
REM Starts both servers in their own windows and opens the app.
REM
REM   backend   http://127.0.0.1:8000   (FastAPI, --reload)
REM   frontend  http://localhost:5173   (Vite, HMR)
REM
REM Vite proxies /api to the backend, so the browser sees a single origin --
REM the same shape Caddy provides in deployment. Close either window to stop
REM that server.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no virtualenv. Run:  python -m venv .venv
    exit /b 1
)
if not exist "frontend\node_modules" (
    echo ERROR: frontend dependencies not installed. Run:
    echo   cd frontend ^&^& npm install
    exit /b 1
)

echo Starting backend on http://127.0.0.1:8000 ...
start "BDSA analyst - backend" cmd /k ""%~dp0.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload"

echo Starting frontend on http://localhost:5173 ...
start "BDSA analyst - frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Give them a few seconds, then open:  http://localhost:5173
echo Close either window to stop that server.
