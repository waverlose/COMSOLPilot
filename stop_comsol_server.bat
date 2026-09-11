@echo off
setlocal
cd /d "%~dp0"
title COMSOLPilot - Stop COMSOL Server

if /I "%~1"=="/?" goto usage
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage

REM User-facing COMSOL Server stopper for the fixed local port workflow.
echo Stopping COMSOL Server for COMSOLPilot...
echo Project: %CD%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_comsol_server.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
    echo COMSOL Server stop command failed. Exit code: %EXITCODE%
) else (
    echo COMSOL Server stop command completed.
)
echo.
pause
exit /b %EXITCODE%

:usage
echo COMSOLPilot COMSOL Server stopper
echo.
echo Usage:
echo   stop_comsol_server.bat
echo   stop_comsol_server.bat -Port 2036
echo   stop_comsol_server.bat -All
echo.
pause
exit /b 0
