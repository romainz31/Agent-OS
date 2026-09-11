@echo off
setlocal
chcp 65001 >nul
title Tests Agent-OS V11.5
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas disponible dans PATH.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0overlay\usr\plugins;%PYTHONPATH%"
python -m unittest tests.test_semantic_intake tests.test_gate_v115
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [OK] Tests semantiques V11.5 passes.
) else (
    echo [ERREUR] Tests V11.5 en echec.
)
pause
exit /b %RC%
