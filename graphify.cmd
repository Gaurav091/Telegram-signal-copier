@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "GRAPHIFY_EXE=%REPO_ROOT%.venv\Scripts\graphify.exe"
set "PYTHON_EXE=%REPO_ROOT%.venv\Scripts\python.exe"

if exist "%GRAPHIFY_EXE%" (
    "%GRAPHIFY_EXE%" %*
    exit /b %ERRORLEVEL%
)

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -m graphify %*
    exit /b %ERRORLEVEL%
)

echo [graphify] Missing project virtualenv at .venv\Scripts. 1>&2
echo [graphify] Run these commands from repo root: 1>&2
echo   python -m venv .venv 1>&2
echo   .venv\Scripts\python.exe -m pip install graphify-cli 1>&2
exit /b 1