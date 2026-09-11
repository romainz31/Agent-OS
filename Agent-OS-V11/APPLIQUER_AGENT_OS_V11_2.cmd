@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Agent-OS V11.2 - Intake semantique Paul
cd /d "%~dp0"

echo.
echo ================================================
echo   AGENT-OS V11.2 - INTAKE SEMANTIQUE DE PAUL
echo ================================================
echo.

if not exist "%~dp0INSTALLER_V11.ps1" (
    echo [ERREUR] INSTALLER_V11.ps1 est introuvable.
    echo Extrais le contenu de ce ZIP directement dans ton dossier Agent-OS-V11.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0overlay\usr\plugins\agent_os_memory\helpers\intake.py" (
    echo [ERREUR] Les fichiers V11.2 ne sont pas presents dans overlay.
    pause
    exit /b 1
)

echo [1/3] Copie de la V11.2 dans Agent-Zero-V11...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 (
    echo.
    echo [ERREUR] La copie du plugin a echoue.
    pause
    exit /b 1
)

echo.
echo [2/3] Verification des fichiers copies...
set "TARGET=%~dp0..\Agent-Zero-V11\usr\plugins\agent_os_memory"
if not exist "%TARGET%\helpers\intake.py" (
    echo [ERREUR] intake.py n'a pas ete copie vers Agent-Zero-V11.
    pause
    exit /b 1
)
if not exist "%TARGET%\extensions\python\message_loop_start\_30_semantic_intake.py" (
    echo [ERREUR] L'extension d'intake n'a pas ete copiee.
    pause
    exit /b 1
)
if not exist "%TARGET%\agents\paul\prompts\agent.system.main.specifics.md" (
    echo [ERREUR] Le prompt principal de Paul n'a pas ete copie.
    pause
    exit /b 1
)
echo [OK] Fichiers V11.2 presents.

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
echo [INFO] Conteneur agent-os-v11 non trouve. Les fichiers sont tout de meme installes.
goto DONE

:NODOCKER
echo [INFO] Docker n'est pas actif. Les fichiers sont tout de meme installes.

:DONE
echo.
echo ================================================
echo   V11.2 INSTALLEE
echo ================================================
echo.
echo IMPORTANT : ouvre un NOUVEAU chat avec le profil Paul.
echo.
echo Premier test :
echo aujourd'hui j'ai nettoye la machine a cafe, la fontaine a chat et les toilettes
echo.
echo Paul doit retenir 3 actions et ne pas refaire sa presentation.
echo.
pause
exit /b 0
