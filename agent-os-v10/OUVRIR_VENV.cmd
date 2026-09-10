@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo [Agent-OS] .venv introuvable. Lance install.cmd d'abord.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
cmd /k
