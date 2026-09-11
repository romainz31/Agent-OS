@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Agent-OS V11.8 - Pipeline semantique Qwen
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"

echo ========================================================
echo       AGENT-OS V11.8 - PIPELINE SEMANTIQUE QWEN
echo ========================================================
if not exist "%~dp0INSTALLER_V11.ps1" goto ERROR_END
if not exist "%A0%" goto ERROR_END

echo [1/4] Installation...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 goto ERROR_END

echo [2/4] Verification fichiers...
findstr /C:"version: 11.8.0" "%PLUGIN%\plugin.yaml" >nul || goto ERROR_END
findstr /C:"current_turn_only" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
findstr /C:"RESOLVER_SYSTEM" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
echo [OK] Fichiers V11.8 presents.

echo [3/4] Redemarrage...
where docker >nul 2>&1 || goto DONE_NO_DOCKER
docker info >nul 2>&1 || goto DONE_NO_DOCKER
docker inspect agent-os-v11 >nul 2>&1 || goto DONE_NO_DOCKER
docker restart agent-os-v11 >nul || goto ERROR_END
timeout /t 4 /nobreak >nul

echo [4/4] Verification runtime...
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; assert hasattr(intake,'RESOLVER_SYSTEM'); assert 'current_turn_only' in open(intake.__file__,encoding='utf-8').read(); print('V11.8 semantic pipeline OK')"
if errorlevel 1 goto ERROR_END

echo.
echo V11.8 installee.
echo Ouvre un NOUVEAU chat Paul et teste :
echo   Coralie est ma copine
echo   ma copine travaille demain matin
echo   qui travaille demain matin ?
echo   mardi j'ai lave ma voiture
echo   qu'est-ce que j'ai fait mardi ?
goto END_OK

:DONE_NO_DOCKER
echo [INFO] Fichiers installes. Lance ensuite DEMARRER_AGENT_OS.cmd.
goto END_OK

:ERROR_END
echo [ERREUR] Installation ou verification V11.8 echouee.
pause
exit /b 1
:END_OK
pause
exit /b 0
