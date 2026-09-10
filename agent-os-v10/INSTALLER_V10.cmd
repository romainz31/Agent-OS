@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Agent-OS] Creation de .venv...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

echo [Agent-OS] Mise a jour de pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

if exist "requirements.txt" (
    echo [Agent-OS] Installation des dependances principales...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

if exist "requirements-documents.txt" (
    echo [Agent-OS] Installation des dependances documents/tests...
    ".venv\Scripts\python.exe" -m pip install -r requirements-documents.txt
    if errorlevel 1 goto :error
)

echo.
echo [Agent-OS] Installation terminee.
pause
exit /b 0

:error
echo.
echo [Agent-OS] Erreur pendant l'installation.
pause
exit /b 1
