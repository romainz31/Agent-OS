@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Lancez INSTALLER.cmd avant de demarrer.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" start_v10.py
pause
