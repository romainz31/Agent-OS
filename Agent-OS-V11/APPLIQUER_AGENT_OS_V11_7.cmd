@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Agent-OS V11.7 - Correctif clarifications Paul
cd /d "%~dp0"

set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"

echo.
echo ========================================================
echo      AGENT-OS V11.7 - CLARIFICATIONS / CONTEXTE
echo ========================================================
echo.

if not exist "%~dp0INSTALLER_V11.ps1" (
    echo [ERREUR] INSTALLER_V11.ps1 introuvable.
    echo Extrais le CONTENU du ZIP directement dans Agent-OS-V11.
    goto ERROR_END
)
if not exist "%A0%" (
    echo [ERREUR] Agent-Zero-V11 introuvable : %A0%
    goto ERROR_END
)

echo [1/4] Installation du plugin V11.7...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 goto ERROR_END

echo [2/4] Verification...
findstr /C:"version: 11.7.0" "%PLUGIN%\plugin.yaml" >nul || goto ERROR_END
findstr /C:"uses_pending" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
findstr /C:"middle_name" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
echo [OK] V11.7 copiee.

echo [3/4] Redemarrage du conteneur...
where docker >nul 2>&1 || goto DONE_NO_DOCKER
docker info >nul 2>&1 || goto DONE_NO_DOCKER
docker inspect agent-os-v11 >nul 2>&1 || goto DONE_NO_DOCKER
docker restart agent-os-v11 >nul || goto ERROR_END
timeout /t 4 /nobreak >nul
echo [OK] Agent-OS redemarre.

echo [4/4] Verification runtime...
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; assert 'uses_pending' in intake.ROUTER_SYSTEM; assert 'middle_name' in intake.CAPTURE_SYSTEM; print('V11.7 intake OK:', intake.__file__)"
if errorlevel 1 goto ERROR_END

echo.
echo ========================================================
echo              V11.7 INSTALLEE
echo ========================================================
echo.
echo Ouvre un NOUVEAU chat Paul et teste dans cet ordre :
echo   mon deuxieme prenom est Michel
echo   Coralie est ma copine
echo   quel est mon deuxieme prenom ?
echo   comment s'appelle ma copine ?
goto END_OK

:DONE_NO_DOCKER
echo [INFO] Fichiers installes. Docker n'est pas disponible actuellement.
echo Lance ensuite DEMARRER_AGENT_OS.cmd.
goto END_OK

:ERROR_END
echo.
echo [ERREUR] Installation ou verification V11.7 echouee.
pause
exit /b 1

:END_OK
echo.
pause
exit /b 0
