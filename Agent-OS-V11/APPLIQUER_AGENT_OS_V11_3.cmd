@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Agent-OS V11.3 - Reponses Paul
cd /d "%~dp0"

echo.
echo ======================================================
echo   AGENT-OS V11.3 - CORRECTIF REPONSES / MEMOIRE PAUL
echo ======================================================
echo.

if not exist "%~dp0INSTALLER_V11.ps1" (
    echo [ERREUR] INSTALLER_V11.ps1 est introuvable.
    echo Extrais le CONTENU de ce ZIP directement dans ton dossier Agent-OS-V11.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0overlay\usr\plugins\agent_os_memory\helpers\intake.py" (
    echo [ERREUR] Les fichiers V11.3 ne sont pas presents dans overlay.
    pause
    exit /b 1
)

if not exist "%~dp0overlay\usr\plugins\agent_os_memory\extensions\python\_functions\agent\AgentContext\_process_chain\start\_30_semantic_intake_gate.py" (
    echo [ERREUR] Le nouveau gate V11.3 est absent.
    pause
    exit /b 1
)

echo [1/3] Installation du correctif V11.3 dans Agent-Zero-V11...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 (
    echo.
    echo [ERREUR] La copie du plugin a echoue.
    pause
    exit /b 1
)

echo.
echo [2/3] Verification...
set "TARGET=%~dp0..\Agent-Zero-V11\usr\plugins\agent_os_memory"
if not exist "%TARGET%\helpers\intake.py" (
    echo [ERREUR] intake.py n'a pas ete copie.
    pause
    exit /b 1
)
if not exist "%TARGET%\extensions\python\_functions\agent\AgentContext\_process_chain\start\_30_semantic_intake_gate.py" (
    echo [ERREUR] Le gate _process_chain V11.3 n'a pas ete copie.
    pause
    exit /b 1
)
if not exist "%TARGET%\extensions\python\message_loop_start\_30_semantic_intake.py" (
    echo [ERREUR] Le neutraliseur de l'ancien intake V11.2 est absent.
    pause
    exit /b 1
)
echo [OK] Correctif V11.3 present.

echo.
echo [3/3] Redemarrage Docker si disponible...
where docker >nul 2>&1
if errorlevel 1 goto NODOCKER

docker info >nul 2>&1
if errorlevel 1 goto NODOCKER

docker inspect agent-os-v11 >nul 2>&1
if errorlevel 1 goto NOCONTAINER

docker restart agent-os-v11 >nul
if errorlevel 1 (
    echo [ATTENTION] Les fichiers sont copies mais le conteneur n'a pas pu etre redemarre.
    goto DONE
)
echo [OK] Conteneur agent-os-v11 redemarre.
goto DONE

:NOCONTAINER
echo [INFO] Conteneur agent-os-v11 non trouve. Les fichiers sont installes.
goto DONE

:NODOCKER
echo [INFO] Docker n'est pas actif. Les fichiers sont installes.

:DONE
echo.
echo ======================================================
echo   V11.3 INSTALLEE
echo ======================================================
echo.
echo La base assistant.db n'a pas ete effacee.
echo Ouvre un NOUVEAU chat avec le profil Paul pour le test.
echo.
echo Test recommande :
echo   coralie est ma copine
echo Puis :
echo   qu'est-ce que j'ai fait aujourd'hui ?
echo.
echo Paul ne doit plus repondre "C'est bien, merci" ni inventer
echo une utilite ou une explication sur l'evenement.
echo.
pause
exit /b 0
