@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Agent-OS V11.9 - Perspective utilisateur
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"

echo ========================================================
echo       AGENT-OS V11.9 - PERSPECTIVE UTILISATEUR
echo ========================================================
if not exist "%~dp0INSTALLER_V11.ps1" goto ERROR_END
if not exist "%A0%" goto ERROR_END

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 goto ERROR_END

findstr /C:"version: 11.9.0" "%PLUGIN%\plugin.yaml" >nul || goto ERROR_END
findstr /C:"_user_to_assistant_perspective" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END

where docker >nul 2>&1 || goto END_OK
docker info >nul 2>&1 || goto END_OK
docker inspect agent-os-v11 >nul 2>&1 || goto END_OK
docker restart agent-os-v11 >nul || goto ERROR_END
timeout /t 4 /nobreak >nul

docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; assert hasattr(intake,'_user_to_assistant_perspective'); print(intake._user_to_assistant_perspective('lave ma voiture')); print('V11.9 OK')"
if errorlevel 1 goto ERROR_END

:END_OK
echo.
echo V11.9 installee.
echo Teste :
echo   mardi j'ai lave ma voiture
echo   qu'est-ce que j'ai fait mardi ?
pause
exit /b 0

:ERROR_END
echo [ERREUR] Installation ou verification V11.9 echouee.
pause
exit /b 1
