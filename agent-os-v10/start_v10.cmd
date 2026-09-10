@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [Agent-OS] Environnement .venv introuvable.
    echo Lance d'abord : install.cmd
    echo.
    pause
    exit /b 1
)

if exist "start_v10.py" (
    ".venv\Scripts\python.exe" "start_v10.py"
    set "RC=%ERRORLEVEL%"
) else if exist "api_server.py" (
    echo [Agent-OS] start_v10.py absent, lancement de api_server.py
    ".venv\Scripts\python.exe" -u "api_server.py"
    set "RC=%ERRORLEVEL%"
) else (
    echo.
    echo [Agent-OS] Impossible de trouver start_v10.py ou api_server.py.
    echo.
    pause
    exit /b 1
)

if not "%RC%"=="0" (
    echo.
    echo [Agent-OS] Le programme s'est termine avec le code %RC%.
    pause
)
exit /b %RC%
