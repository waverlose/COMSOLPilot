@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title COMSOLPilot - COMSOL server launcher
chcp 65001 >nul

REM ---------------------------------------------------------------------------
REM One-click launcher for the COMSOLPilot COMSOL server.
REM
REM   1  GUI mode        start the server, then open COMSOL Desktop so you
REM                    can attach to it and watch the AI work.
REM   2  Headless mode   start the server only, no windows at all.
REM   3  Port setup      choose the server port (saved for future launches).
REM   4  Stop            shut the server down.
REM
REM First run: creates .venv and installs dependencies automatically (once).
REM
REM Direct commands (no menu, no pause):
REM   start_comsol_server.bat gui | headless | status | stop | setport 2040
REM ---------------------------------------------------------------------------

set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File"
set "SCRIPTS=%~dp0scripts"
set "SETTINGS=%~dp0workspace\settings.json"

REM ---------------------------------------------------------------------------
REM First run: build the Python environment if it does not exist yet.
REM ---------------------------------------------------------------------------
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto have_venv

echo First run detected - setting up the Python environment.
echo This installs dependencies once and takes 3-5 minutes.
echo.
set "BASE_PY="
REM Prefer a Python that has wheels for the pinned numpy line (3.10-3.12).
py -3.12 -c "print()" >nul 2>nul
if not errorlevel 1 if not defined BASE_PY set "BASE_PY=py -3.12"
py -3.11 -c "print()" >nul 2>nul
if not errorlevel 1 if not defined BASE_PY set "BASE_PY=py -3.11"
py -3.10 -c "print()" >nul 2>nul
if not errorlevel 1 if not defined BASE_PY set "BASE_PY=py -3.10"
py -3.13 -c "print()" >nul 2>nul
if not errorlevel 1 if not defined BASE_PY set "BASE_PY=py -3.13"
if not defined BASE_PY (
    where python >nul 2>nul && set "BASE_PY=python"
)
if "%BASE_PY%"=="" (
    echo [!] Python was not found on this computer.
    echo     Install Python 3.10 or newer from https://www.python.org/downloads/
    echo     tick "Add python.exe to PATH" during setup, then run this file again.
    call :finish
    exit /b 1
)
%BASE_PY% -m venv "%~dp0.venv"
if not exist "%PY%" (
    echo [!] Failed to create the Python environment. See messages above.
    call :finish
    exit /b 1
)
"%PY%" -m pip install --upgrade pip -q
"%PY%" -m pip install -r "%~dp0requirements-windows.txt" -q
if errorlevel 1 (
    echo [!] Dependency installation failed. Check your network/proxy and re-run.
    call :finish
    exit /b 1
)
echo Environment ready.
echo.

:have_venv

REM ---------------------------------------------------------------------------
REM Prefer Windows Terminal: the menu uses Unicode block glyphs that render
REM poorly in the legacy console. Relaunch once (WT_SESSION prevents a loop).
REM NOTE: no -d argument here. WT's arg parser mangles "start"-forwarded
REM quotes and then fails with 0x8007010b on the starting directory; the bat
REM does "cd /d %~dp0" on its own first line anyway.
REM ---------------------------------------------------------------------------
if defined WT_SESSION goto wt_done
if not "%~1"=="" goto wt_done
set "WT_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe"
if not exist "%WT_EXE%" goto wt_done
"%WT_EXE%" cmd /c "%~f0"
exit /b 0
:wt_done

REM ---------------------------------------------------------------------------
REM Port resolution: COMSOL_PORT env wins; otherwise workspace\settings.json;
REM otherwise the default 2036.
REM ---------------------------------------------------------------------------
set "PORT=2036"
if not "%COMSOL_PORT%"=="" (
    set "PORT=%COMSOL_PORT%"
    goto port_done
)
if not exist "%SETTINGS%" goto port_done
for /f "usebackq delims=" %%i in (`"%PY%" -c "import json,sys;print(json.load(open(sys.argv[1])).get('port',2036))" "%SETTINGS%"`) do set "PORT=%%i"
:port_done

REM No arguments -> animated Python menu. With arguments we are
REM being scripted, so we stay quiet and do not block.
set "INTERACTIVE=1"
if not "%~1"=="" set "INTERACTIVE="

if "%~1"=="" (
    "%PY%" "%SCRIPTS%\launcher.py"
    exit /b 0
)

if /I "%~1"=="gui"      goto do_gui
if /I "%~1"=="headless" goto do_headless
if /I "%~1"=="status"   goto do_status
if /I "%~1"=="stop"     goto do_stop
if /I "%~1"=="setport"  goto do_setport
if /I "%~1"=="/?"       goto usage
if /I "%~1"=="-h"       goto usage
if /I "%~1"=="--help"   goto usage
if not "%~1"==""        goto do_passthrough

:do_gui
call :start_server -OpenDesktop
goto after

:do_headless
call :start_server
goto after

:do_status
echo.
echo Querying COMSOL Server status ...
echo.
%PS% "%SCRIPTS%\comsol_status.ps1" -Port %PORT%
echo.
echo Checking the MCP client port ...
"%PY%" "%SCRIPTS%\sync_mcp_port.py" --dry-run
call :finish
exit /b 0

:do_stop
echo.
echo Stopping every COMSOL Server process ...
echo.
%PS% "%SCRIPTS%\stop_comsol_server.ps1" -All
call :finish
exit /b 0

REM setport: interactive (no argument) or direct: start_comsol_server.bat setport 2040
:do_setport
set "NEWPORT=%~2"
if "%NEWPORT%"=="" (
    echo.
    echo Current port: %PORT%
    set /p "NEWPORT=New port (1024-65535, Enter keeps %PORT%): "
)
if "%NEWPORT%"=="" set "NEWPORT=%PORT%"
echo.
"%PY%" "%SCRIPTS%\set_port.py" %NEWPORT%
if errorlevel 1 (
    call :finish
    exit /b 1
)
echo.
echo Syncing the new port to installed MCP clients ...
"%PY%" "%SCRIPTS%\sync_mcp_port.py" --port %NEWPORT%
echo.
echo Restart the server (menu 4, then 1 or 2) to move it to port %NEWPORT%.
call :finish
exit /b 0

:do_passthrough
REM Legacy behaviour: forward the raw arguments to the startup script.
%PS% "%SCRIPTS%\start_comsol_server.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo [!] COMSOL Server startup failed. Exit code: %RC%
    echo     Logs: %~dp0workspace\logs
) else (
    "%PY%" "%SCRIPTS%\sync_mcp_port.py"
)
call :finish
exit /b %RC%

:after
echo.
echo ------------------------------------------------------------
echo  Next steps
echo ------------------------------------------------------------
echo  The server must be running BEFORE the MCP client connector
echo  starts. If the client was already open, toggle the
echo  'comsolpilot' connector off and on once so it reconnects.
echo ------------------------------------------------------------
call :finish
exit /b 0

REM ---------------------------------------------------------------------------
REM :start_server [extra powershell arguments]
REM ---------------------------------------------------------------------------
:start_server
echo.
echo Starting COMSOL Server on port %PORT% ...
echo.
%PS% "%SCRIPTS%\start_comsol_server.ps1" -Port %PORT% %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [!] COMSOL Server did not start. Exit code: %RC%
    echo     Check the newest log in %~dp0workspace\logs
    goto :eof
)
echo.
echo Keeping the MCP clients pointed at the right port ...
"%PY%" "%SCRIPTS%\sync_mcp_port.py"
goto :eof

REM :finish pauses only when the launcher was opened interactively.
:finish
if defined INTERACTIVE (
    echo.
    pause
)
goto :eof

:end
exit /b 0

:usage
echo COMSOLPilot - COMSOL server launcher
echo.
echo Usage:
echo   start_comsol_server.bat                interactive menu
echo   start_comsol_server.bat gui            server + COMSOL Desktop
echo   start_comsol_server.bat headless       server only, no window
echo   start_comsol_server.bat status         report server and port
echo   start_comsol_server.bat stop           shut the server down
echo   start_comsol_server.bat setport 2040   change the saved port
echo.
echo Environment overrides:
echo   COMSOL_PORT           server port (default from workspace\settings.json, else 2036)
echo   COMSOL_SERVER_EXE     full path to comsolmphserver.exe
echo   COMSOL_DESKTOP_EXE    full path to comsol.exe
echo.
echo Advanced: any other arguments go straight to
echo   scripts\start_comsol_server.ps1
echo   e.g. start_comsol_server.bat -Port 2037 -Cores 4
echo.
call :finish
exit /b 0
