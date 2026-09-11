@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Agent-OS V11.5 - Semantic Gate
cd /d "%~dp0"

set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"
set "USR_EXT=%A0%\usr\extensions\python\_functions\agent\AgentContext\_process_chain\start"
set "SRC_EXT=%~dp0overlay\usr\extensions\python\_functions\agent\AgentContext\_process_chain\start\_05_agent_os_personal_intake.py"

echo.
echo ========================================================
echo    AGENT-OS V11.5 - CORRECTIF PAUL / MEMOIRE SEMANTIQUE
echo ========================================================
echo.

if not exist "%~dp0INSTALLER_V11.ps1" (
    echo [ERREUR] INSTALLER_V11.ps1 introuvable.
    echo Extrais le CONTENU du ZIP directement dans Agent-OS-V11.
    goto ERROR_END
)
if not exist "%SRC_EXT%" (
    echo [ERREUR] Le gate V11.5 est absent du ZIP.
    goto ERROR_END
)
if not exist "%A0%" (
    echo [ERREUR] Agent-Zero-V11 introuvable :
    echo %A0%
    goto ERROR_END
)

echo [1/5] Installation du plugin V11.5...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 goto INSTALL_ERROR

echo.
echo [2/5] Installation du gate GLOBAL avant la boucle LLM...
if not exist "%USR_EXT%" mkdir "%USR_EXT%"
copy /Y "%SRC_EXT%" "%USR_EXT%\_05_agent_os_personal_intake.py" >nul
if errorlevel 1 goto COPY_ERROR

echo [OK] Gate global copie.

echo.
echo [3/5] Verification des fichiers...
if not exist "%PLUGIN%\helpers\intake.py" goto COPY_ERROR
if not exist "%PLUGIN%\agents\paul\prompts\agent.system.main.specifics.md" goto COPY_ERROR
if not exist "%PLUGIN%\agents\paul\extensions\python\agent_init\_20_paul_identity.py" goto COPY_ERROR
if not exist "%USR_EXT%\_05_agent_os_personal_intake.py" goto COPY_ERROR
findstr /C:"version: 11.5.0" "%PLUGIN%\plugin.yaml" >nul || goto COPY_ERROR
findstr /C:"PAUL_IDENTITY_GUARD_V11_5" "%PLUGIN%\agents\paul\prompts\agent.system.main.specifics.md" >nul || goto COPY_ERROR
echo [OK] Fichiers V11.5 verifies.

echo.
echo [4/5] Redemarrage Docker / Agent-OS...
where docker >nul 2>&1
if errorlevel 1 (
    echo [INFO] Docker n'est pas disponible maintenant. Les fichiers sont installes.
    echo Lance ensuite DEMARRER_AGENT_OS.cmd.
    goto DONE_NO_RUNTIME
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [INFO] Docker n'est pas demarre. Les fichiers sont installes.
    echo Lance ensuite DEMARRER_AGENT_OS.cmd.
    goto DONE_NO_RUNTIME
)

docker inspect agent-os-v11 >nul 2>&1
if errorlevel 1 (
    echo [INFO] Le conteneur agent-os-v11 n'existe pas ou n'est pas accessible.
    goto DONE_NO_RUNTIME
)

docker restart agent-os-v11 >nul
if errorlevel 1 goto DOCKER_ERROR

echo [OK] agent-os-v11 redemarre.
timeout /t 4 /nobreak >nul

echo.
echo [5/5] TEST RUNTIME : Agent Zero voit-il vraiment le gate ?
docker exec agent-os-v11 /opt/venv-a0/bin/python -c "from helpers import subagents,extension; point='_functions/agent/AgentContext/_process_chain/start'; paths=subagents.get_paths(None,'extensions/python',*point.split('/')); print('PATHS=',paths); classes=extension._get_extension_classes(point,agent=None); names=[c.__name__ for c in classes]; print('CLASSES=',names); assert 'AgentOSPersonalIntakeGate' in names, 'Gate V11.5 non charge'"
if errorlevel 1 goto RUNTIME_ERROR

echo [OK] Gate V11.5 charge par le vrai runtime Agent Zero.

echo.
echo [INFO] Version plugin dans le conteneur :
docker exec agent-os-v11 sh -lc "grep -E '^(version|always_enabled):' /a0/usr/plugins/agent_os_memory/plugin.yaml"

goto DONE

:DONE_NO_RUNTIME
echo.
echo ========================================================
echo   V11.5 INSTALLEE - verification runtime a faire au lancement
 echo ========================================================
echo.
echo Au prochain demarrage, lance DIAGNOSTIQUER_AGENT_OS_V11_5.cmd
 echo pour verifier que le gate est bien charge.
goto END_OK

:DONE
echo.
echo ========================================================
echo                 V11.5 INSTALLEE ET VERIFIEE
 echo ========================================================
echo.
echo IMPORTANT : ouvre un NOUVEAU chat Paul.
echo.
echo Test 1 :
echo   je mapelle romain et jhabite a brens
echo Attendu :
echo   D'accord, je retiens que tu t'appelles Romain et que tu habites a Brens.
echo.
echo Test 2 :
echo   aujourd'hui j'ai nettoye la machine a cafe, la fontaine a chat et les toilettes
echo Attendu : Paul repond avec "tu as nettoye...", jamais "j'ai nettoye...".
echo.
echo Un log local de diagnostic est cree ici :
echo   Agent-Zero-V11\usr\agent_os_memory\intake_runtime.log

goto END_OK

:INSTALL_ERROR
echo [ERREUR] INSTALLER_V11.ps1 a echoue.
goto ERROR_END
:COPY_ERROR
echo [ERREUR] Copie ou verification des fichiers V11.5 impossible.
goto ERROR_END
:DOCKER_ERROR
echo [ERREUR] Impossible de redemarrer agent-os-v11.
goto ERROR_END
:RUNTIME_ERROR
echo.
echo [ERREUR] Les fichiers sont presents MAIS Agent Zero ne charge pas le gate.
echo C'est exactement le probleme que les anciennes versions ne detectaient pas.
echo Lance DIAGNOSTIQUER_AGENT_OS_V11_5.cmd et copie-moi le resultat.
goto ERROR_END

:END_OK
echo.
pause
exit /b 0

:ERROR_END
echo.
pause
exit /b 1
