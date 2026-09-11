@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Agent-OS V12.1 - Memoire episodique + clarification intelligente
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"

echo ========================================================
echo   AGENT-OS V12.1 - MEMOIRE + CLARIFICATION INTELLIGENTE
echo ========================================================
if not exist "%~dp0INSTALLER_V11.ps1" goto ERROR_END
if not exist "%A0%" goto ERROR_END

echo [1/4] Installation...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 goto ERROR_END

echo [2/4] Verification...
findstr /C:"version: 12.1.0" "%PLUGIN%\plugin.yaml" >nul || goto ERROR_END
findstr /C:"AMBIGUITY_MATCHER_SYSTEM" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
findstr /C:"memory_candidate_confirmation" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
findstr /C:"source_text" "%PLUGIN%\helpers\intake.py" >nul || goto ERROR_END
echo [OK] Fichiers V12.1 presents.

echo [3/4] Redemarrage...
where docker >nul 2>&1 || goto DONE_NO_DOCKER
docker info >nul 2>&1 || goto DONE_NO_DOCKER
docker inspect agent-os-v11 >nul 2>&1 || goto DONE_NO_DOCKER
docker restart agent-os-v11 >nul || goto ERROR_END
timeout /t 4 /nobreak >nul

echo [4/4] Verification runtime...
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; assert hasattr(intake,'AMBIGUITY_MATCHER_SYSTEM'); assert hasattr(intake,'AMBIGUITY_CONFIRMATION_SYSTEM'); print('V12.1 memory clarification OK')"
if errorlevel 1 goto ERROR_END

echo.
echo V12.1 installee.
echo Ouvre un NOUVEAU chat Paul.
goto END_OK

:DONE_NO_DOCKER
echo [INFO] Les fichiers sont installes. Lance ensuite DEMARRER_AGENT_OS.cmd.
goto END_OK

:ERROR_END
echo [ERREUR] Installation ou verification V12.1 echouee.
pause
exit /b 1
:END_OK
pause
exit /b 0
