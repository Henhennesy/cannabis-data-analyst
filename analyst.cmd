@echo off
REM Launcher for the BDSA analyst CLI.
REM
REM Exists because this machine's home directory contains a literal backtick
REM (C:\Users\Mike`), which is PowerShell's escape character -- any absolute
REM path to this project inside double quotes silently mangles itself. A .cmd
REM file sidesteps that entirely: cmd.exe has no backtick escaping, and %~dp0
REM resolves to this script's own folder, so the working directory no longer
REM matters. Run it from anywhere.
REM
REM Usage:
REM   analyst.cmd                          interactive session
REM   analyst.cmd --ask "your question"    one question, then exit

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no virtualenv at "%~dp0.venv"
    echo Create it with:  python -m venv .venv
    echo Then:            .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    exit /b 1
)

if not exist ".env" (
    echo ERROR: no .env at "%~dp0.env"
    echo Copy .env.example to .env and fill it in.
    exit /b 1
)

".venv\Scripts\python.exe" "backend\cli.py" %*
