@echo off
setlocal
cd /d "%~dp0"
if "%COMSOL_HOST%"=="" set COMSOL_HOST=localhost
if "%COMSOL_PORT%"=="" set COMSOL_PORT=2036
REM Use a fixed COMSOL Server by default; this is the simplest path for new users.
if "%COMSOL_MODE%"=="" set COMSOL_MODE=gui
if "%COMSOL_PYTHON%"=="" (
    REM Prefer the project-local environment created by setup_windows.ps1.
    if exist "%~dp0.venv\Scripts\python.exe" (
        set COMSOL_PYTHON=%~dp0.venv\Scripts\python.exe
    ) else (
        set COMSOL_PYTHON=python
    )
)

REM MCP uses stdout for JSON-RPC; startup diagnostics must go to stderr.
echo COMSOLPilot mode: %COMSOL_MODE% 1>&2
echo COMSOL fixed port: %COMSOL_HOST%:%COMSOL_PORT% 1>&2
"%COMSOL_PYTHON%" -m src.server
