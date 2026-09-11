@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Correctif Paul - Agent-OS V11.1

set "ROOT=%~dp0"

echo.
echo ==========================================
echo       CORRECTIF PAUL - AGENT-OS V11.1
echo ==========================================
echo.

if not exist "%ROOT%INSTALLER_V11.ps1" (
    echo [ERREUR] Ce correctif doit etre extrait dans le dossier Agent-OS-V11.
    echo [INFO] Le fichier INSTALLER_V11.ps1 doit se trouver a cote de ce .cmd.
    echo.
    pause
    exit /b 1
)

echo [INFO] Mise a jour du plugin et du profil Paul...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%INSTALLER_V11.ps1" -SkipClone
if errorlevel 1 (
    echo.
    echo [ERREUR] L'installation du correctif a echoue.
    pause
    exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 goto DONE

docker info >nul 2>&1
if errorlevel 1 goto DONE

docker inspect agent-os-v11 >nul 2>&1
if errorlevel 1 goto DONE

echo [INFO] Redemarrage du conteneur agent-os-v11...
docker restart agent-os-v11 >nul
if errorlevel 1 (
    echo [ATTENTION] Le plugin a ete copie, mais le conteneur n'a pas pu etre redemarre.
    goto DONE
)
echo [OK] Conteneur redemarre.

:DONE
echo.
echo [OK] Correctif Paul installe.
echo [IMPORTANT] Dans Agent Zero, ouvre un NOUVEAU chat avec le profil Paul.
echo [TEST] Ecris ensuite : "je m'appelle Romain et j'habite a Brens dans le Tarn".
echo.
pause
exit /b 0
