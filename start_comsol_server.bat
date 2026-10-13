@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title COMSOLPilot
chcp 936 >nul

REM ===========================================================================
REM  COMSOLPilot - COMSOL server launcher
REM
REM    start_comsol_server.bat            menu
REM    start_comsol_server.bat headless   server only, no window
REM    start_comsol_server.bat gui        server + COMSOL Desktop
REM    start_comsol_server.bat restart    stop, then start per config.toml
REM    start_comsol_server.bat stop       shut the server down
REM    start_comsol_server.bat status     report server and port
REM
REM  Port, COMSOL version, mode and spinner live in config.toml; menu items
REM  5 and 6 write to it. The first run creates .venv and installs the
REM  dependencies (once, 3-5 minutes).
REM
REM  NOTE: this file is GBK-encoded on purpose. cmd.exe re-reads a batch file by
REM  byte offset, so a UTF-8 file (or a mid-file chcp) desynchronises its parser.
REM  A literal pipe in the banner is escaped as ^| for the same reason.
REM ===========================================================================

set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File"
set "SCRIPTS=%~dp0scripts"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" call :bootstrap
if not exist "%PY%" exit /b 1

REM Port: COMSOL_PORT wins, otherwise config.toml, otherwise 2036.
REM ("for /f" chokes on a quoted program path, so read through a temp file.)
set "PORT="
if not "%COMSOL_PORT%"=="" set "PORT=%COMSOL_PORT%"
if not "%PORT%"=="" goto port_ready
set "CFGPORT=%TEMP%\comsolpilot_port_%RANDOM%.txt"
"%PY%" "%SCRIPTS%\show_config.py" comsol port > "%CFGPORT%" 2>nul
if exist "%CFGPORT%" set /p PORT=<"%CFGPORT%"
if exist "%CFGPORT%" del "%CFGPORT%" >nul 2>nul
:port_ready
if "%PORT%"=="" set "PORT=2036"

set "INTERACTIVE="
if "%~1"=="" set "INTERACTIVE=1"

if "%~1"==""           goto menu
if /I "%~1"=="headless" goto headless
if /I "%~1"=="gui"      goto gui
if /I "%~1"=="restart"  goto restart
if /I "%~1"=="status"   goto status
if /I "%~1"=="stop"     goto stop
if /I "%~1"=="/?"       goto usage
if /I "%~1"=="-h"       goto usage
if /I "%~1"=="--help"   goto usage
echo Unknown option: %~1
goto usage

REM ---------------------------------------------------------------------------
REM  Menu
REM ---------------------------------------------------------------------------
:menu
REM The menu is drawn by Python so it can use colour and aligned columns.
REM Its exit code is the chosen item: 0 quit, 1..6 actions, 255 redraw.
"%PY%" "%SCRIPTS%\menu.py"
set "PICK=%ERRORLEVEL%"
if "%PICK%"=="0" exit /b 0
if "%PICK%"=="1" goto headless
if "%PICK%"=="2" goto gui
if "%PICK%"=="3" goto stop
if "%PICK%"=="4" goto restart
if "%PICK%"=="5" goto setport
if "%PICK%"=="6" goto setversion
goto menu

:headless
call :start_server
goto done

:gui
call :start_server -OpenDesktop
goto done

:restart
echo    停止服务 ...
%PS% "%SCRIPTS%\stop_comsol_server.ps1" -All
call :start_configured
goto done

:stop
echo    停止服务 ...
%PS% "%SCRIPTS%\stop_comsol_server.ps1" -All
goto done

:status
%PS% "%SCRIPTS%\comsol_status.ps1" -Port %PORT%
goto done

:setport
"%PY%" "%SCRIPTS%\set_port.py"
goto done

:setversion
"%PY%" "%SCRIPTS%\set_version.py"
goto done

:done
echo.
if not defined INTERACTIVE exit /b 0
echo    按任意键返回菜单 ...
pause >nul
goto menu

REM ---------------------------------------------------------------------------
REM  Helpers
REM ---------------------------------------------------------------------------
:start_server
"%PY%" "%SCRIPTS%\spinner.py" --message "正在启动 COMSOL 服务端" --after "服务运行中  端口 %PORT%" -- %PS% "%SCRIPTS%\start_comsol_server.ps1" -Port %PORT% %*
set "RC=%ERRORLEVEL%"
REM 3 = the user pressed a key; the start continues in the background.
if "%RC%"=="3" goto :eof
if not "%RC%"=="0" goto start_failed
echo    服务端已就绪。
goto :eof

:start_failed
echo    [!] 启动失败（退出码 %RC%），日志见 workspace\logs
goto :eof

:start_configured
set "MODE="
if not "%COMSOL_MODE%"=="" set "MODE=%COMSOL_MODE%"
if not "%MODE%"=="" goto mode_ready
set "CFGMODE=%TEMP%\comsolpilot_mode_%RANDOM%.txt"
"%PY%" "%SCRIPTS%\show_config.py" comsol mode > "%CFGMODE%" 2>nul
if exist "%CFGMODE%" set /p MODE=<"%CFGMODE%"
if exist "%CFGMODE%" del "%CFGMODE%" >nul 2>nul
:mode_ready
if /I "%MODE%"=="headless" (
    call :start_server
) else (
    call :start_server -OpenDesktop
)
goto :eof

REM ---------------------------------------------------------------------------
REM  First run: build the Python environment.
REM ---------------------------------------------------------------------------
:bootstrap
echo.
echo    首次运行：正在创建 Python 环境并安装依赖（约 3-5 分钟，仅一次）。
echo.
set "BASE_PY="
for %%V in (3.12 3.11 3.10 3.13) do (
    if not defined BASE_PY (
        py -%%V -c "print()" >nul 2>nul
        if not errorlevel 1 set "BASE_PY=py -%%V"
    )
)
if not defined BASE_PY (
    where python >nul 2>nul
    if not errorlevel 1 set "BASE_PY=python"
)
if not defined BASE_PY (
    echo    [!] 没有找到 Python，请安装 Python 3.10 或更新版本：
    echo        https://www.python.org/downloads/
    goto :eof
)
%BASE_PY% -m venv "%~dp0.venv"
if not exist "%PY%" (
    echo    [!] 创建 Python 环境失败，见上面的提示。
    goto :eof
)
"%PY%" -m pip install --no-cache-dir -r "%~dp0requirements-windows.txt" -q
if errorlevel 1 (
    echo    [!] 依赖安装失败，请检查网络或代理后重试。
    goto :eof
)
echo    环境已就绪。
goto :eof

:usage
echo.
echo    COMSOLPilot - COMSOL server launcher
echo.
echo      start_comsol_server.bat            menu
echo      start_comsol_server.bat headless   server only, no window
echo      start_comsol_server.bat gui        server + COMSOL Desktop
echo      start_comsol_server.bat restart    stop, then start per config.toml
echo      start_comsol_server.bat status     report server and port
echo      start_comsol_server.bat stop       shut the server down
echo.
echo    配置在 config.toml（端口 / 版本 / 模式 / 动画；菜单 5、6 可直接改）。
echo.
exit /b 0

