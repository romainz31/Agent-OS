@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Agent-OS] .venv introuvable. Lance INSTALLER_V10.cmd d'abord.
    pause
    exit /b 1
)

echo ============================================================
echo TESTS V10.2.1
echo ============================================================
".venv\Scripts\python.exe" -m unittest -v tests.test_v10
if errorlevel 1 goto :error

echo.
echo ============================================================
echo TEST API
echo ============================================================
".venv\Scripts\python.exe" -m tests.test_v10_api
if errorlevel 1 goto :error

echo.
echo [Agent-OS] Tous les tests V10.2.1 sont passes.
pause
exit /b 0

:error
echo.
echo [Agent-OS] Au moins un test a echoue. Copie le texte de cette fenetre dans ChatGPT.
pause
exit /b 1
