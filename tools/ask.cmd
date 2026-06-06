@echo off
REM Windows batch launcher for deepseek_booster.py
REM Usage: ask "what is quantum computing?"
REM        ask --ollama "compare Go vs Rust"
REM        ask --help

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "VENV_PY=%PROJECT_DIR%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo ERROR: Virtual environment python not found at %VENV_PY%
    echo Run this from the project root, or activate the venv first.
    exit /b 1
)

"%VENV_PY%" "%SCRIPT_DIR%deepseek_booster.py" %*
