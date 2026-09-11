@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Tests Agent-OS V11.2
cd /d "%~dp0"

echo.
echo ================================================
echo       TESTS AGENT-OS V11.2
echo ================================================
echo.

where py >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto RUN
)
where python >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto RUN
)

echo [ERREUR] Python n'est pas disponible sur Windows.
pause
exit /b 1

:RUN
set "PYTHONPATH=%~dp0overlay\usr\plugins"
%PY% -m unittest tests.test_semantic_intake -v
if errorlevel 1 (
    echo.
    echo [ERREUR] Au moins un test V11.2 a echoue.
    pause
    exit /b 1
)

echo.
echo [OK] Tests V11.2 reussis.
pause
exit /b 0
