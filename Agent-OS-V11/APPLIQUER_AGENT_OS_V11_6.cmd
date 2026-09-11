@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Agent-OS V11.6 - Correctif extracteur Qwen
cd /d "%~dp0"

set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"
set "USR_EXT=%A0%\usr\extensions\python\_functions\agent\AgentContext\_process_chain\start"
set "SRC_EXT=%~dp0overlay\usr\extensions\python\_functions\agent\AgentContext\_process_chain\start\_05_agent_os_personal_intake.py"

echo.
echo ========================================================
echo      AGENT-OS V11.6 - CORRECTIF EXTRACTEUR QWEN
echo ========================================================
echo.

if not exist "%~dp0INSTALLER_V11.ps1" (
    echo [ERREUR] INSTALLER_V11.ps1 introuvable.
    echo Extrais le CONTENU du ZIP directement dans Agent-OS-V11.
    goto ERROR_END
)
if not exist "%SRC_EXT%" (
    echo [ERREUR] Le gate V11.6 est absent du correctif.
    goto ERROR_END
)
if not exist "%A0%" (
    echo [ERREUR] Agent-Zero-V11 introuvable :
    echo %A0%
    goto ERROR_END
)

echo [1/6] Installation du plugin V11.6...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 goto INSTALL_ERROR

echo.
echo [2/6] Installation du gate global...
if not exist "%USR_EXT%" mkdir "%USR_EXT%"
copy /Y "%SRC_EXT%" "%USR_EXT%\_05_agent_os_personal_intake.py" >nul
if errorlevel 1 goto COPY_ERROR

echo [OK] Gate global copie.

echo.
echo [3/6] Verification des fichiers V11.6...
if not exist "%PLUGIN%\helpers\intake.py" goto COPY_ERROR
if not exist "%PLUGIN%\agents\paul\prompts\agent.system.main.specifics.md" goto COPY_ERROR
findstr /C:"version: 11.6.0" "%PLUGIN%\plugin.yaml" >nul || goto COPY_ERROR
findstr /C:"PAUL_IDENTITY_GUARD_V11_6" "%PLUGIN%\agents\paul\prompts\agent.system.main.specifics.md" >nul || goto COPY_ERROR
findstr /C:"CORRECTION_OBLIGATOIRE" "%PLUGIN%\helpers\intake.py" >nul || goto COPY_ERROR
findstr /C:"_repair_obvious_capture_structure" "%PLUGIN%\helpers\intake.py" >nul || goto COPY_ERROR
echo [OK] Fichiers V11.6 verifies.

echo.
echo [4/6] Archivage de l'ancien log intake...
if exist "%A0%\usr\agent_os_memory\intake_runtime.log" (
    copy /Y "%A0%\usr\agent_os_memory\intake_runtime.log" "%A0%\usr\agent_os_memory\intake_runtime_v115.log" >nul
    del /Q "%A0%\usr\agent_os_memory\intake_runtime.log" >nul 2>&1
    echo [OK] Ancien log conserve sous intake_runtime_v115.log
) else (
    echo [INFO] Aucun ancien log a archiver.
)

echo.
echo [5/6] Redemarrage Agent-OS si Docker est disponible...
where docker >nul 2>&1
if errorlevel 1 goto DONE_NO_RUNTIME

docker info >nul 2>&1
if errorlevel 1 goto DONE_NO_RUNTIME

docker inspect agent-os-v11 >nul 2>&1
if errorlevel 1 goto DONE_NO_RUNTIME

docker restart agent-os-v11 >nul
if errorlevel 1 goto DOCKER_ERROR

echo [OK] agent-os-v11 redemarre.
timeout /t 4 /nobreak >nul

echo.
echo [6/6] Verification dans le vrai runtime Agent Zero...
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from helpers import subagents,extension; from usr.plugins.agent_os_memory.helpers import intake; point='_functions/agent/AgentContext/_process_chain/start'; names=[c.__name__ for c in extension._get_extension_classes(point,agent=None)]; print('CLASSES=',names); print('INTAKE=',intake.__file__); print('RETRY=',hasattr(intake,'_retry_prompt')); print('PROMPT_OK=', 'Romain habite' in intake.CAPTURE_SYSTEM); assert 'AgentOSPersonalIntakeGate' in names; assert hasattr(intake,'_retry_prompt'); assert 'Romain habite' in intake.CAPTURE_SYSTEM"
if errorlevel 1 goto RUNTIME_ERROR

echo [OK] Gate et extracteur V11.6 charges par Agent Zero.
goto DONE

:DONE_NO_RUNTIME
echo [INFO] Docker n'est pas disponible maintenant.
echo Les fichiers V11.6 sont installes. Lance ensuite DEMARRER_AGENT_OS.cmd.
goto END_OK

:DONE
echo.
echo ========================================================
echo              V11.6 INSTALLEE ET VERIFIEE
echo ========================================================
echo.
echo Ouvre un NOUVEAU chat Paul puis teste :
echo.
echo   je mapelle romain et jhabite a brens
echo.
echo puis :
echo.
echo   aujourd'hui j'ai fait du nettoyage et plus particulierement,
echo   j'ai nettoye la machine a cafe, la fontaine a chat et les toilettes
echo.
echo Si cela echoue encore, lance DIAGNOSTIQUER_AGENT_OS_V11_6.cmd.
goto END_OK

:INSTALL_ERROR
echo [ERREUR] INSTALLER_V11.ps1 a echoue.
goto ERROR_END

:COPY_ERROR
echo [ERREUR] Copie ou verification des fichiers V11.6 impossible.
goto ERROR_END

:DOCKER_ERROR
echo [ERREUR] Impossible de redemarrer agent-os-v11.
goto ERROR_END

:RUNTIME_ERROR
echo [ERREUR] Les fichiers sont presents mais le runtime ne charge pas V11.6 correctement.
echo Lance DIAGNOSTIQUER_AGENT_OS_V11_6.cmd et copie le resultat.
goto ERROR_END

:END_OK
echo.
pause
exit /b 0

:ERROR_END
echo.
pause
exit /b 1
