@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Installation terminee. Lancez DEMARRER.cmd.
pause
exit /b 0
:fail
echo Installation interrompue. Copier le message d'erreur du terminal.
pause
exit /b 1
