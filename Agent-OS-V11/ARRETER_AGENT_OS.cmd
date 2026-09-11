@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Agent-OS V11 - Arret

set "CONTAINER=agent-os-v11"

echo.
echo ==========================================
echo          AGENT-OS V11 - ARRET
echo ==========================================
echo.

where docker >nul 2>&1
if errorlevel 1 goto DOCKER_NOT_FOUND

echo [INFO] Verification d'Agent-OS...

docker info >nul 2>&1
if errorlevel 1 (
    echo [INFO] Le moteur Docker ne repond pas.
    echo [INFO] Tentative de fermeture de Docker Desktop...
    goto STOP_DOCKER_DESKTOP
)

docker inspect "%CONTAINER%" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Le conteneur "%CONTAINER%" n'existe pas.
    goto STOP_DOCKER_DESKTOP
)

set "RUNNING="
for /f "delims=" %%S in ('docker inspect -f "{{.State.Running}}" "%CONTAINER%" 2^>nul') do set "RUNNING=%%S"

if /I "!RUNNING!"=="true" (
    echo [INFO] Arret propre d'Agent-OS...
    docker stop -t 30 "%CONTAINER%" >nul 2>&1

    if errorlevel 1 (
        echo [ERREUR] Impossible d'arreter proprement "%CONTAINER%".
        echo Docker Desktop ne sera pas ferme pour eviter une coupure brutale.
        goto ERROR_END
    )

    echo [OK] Agent-OS est arrete.
) else (
    echo [OK] Agent-OS etait deja arrete.
)

:STOP_DOCKER_DESKTOP
echo [INFO] Fermeture de Docker Desktop...

docker desktop stop >nul 2>&1
if not errorlevel 1 goto DOCKER_STOPPED

rem Compatibilite avec certaines installations plus anciennes de Docker Desktop.
set "DOCKERCLI=%ProgramFiles%\Docker\Docker\DockerCli.exe"
if exist "%DOCKERCLI%" (
    echo [INFO] La commande Docker Desktop CLI n'est pas disponible.
    echo [INFO] Utilisation de DockerCli.exe...
    "%DOCKERCLI%" -Shutdown >nul 2>&1
    timeout /t 3 /nobreak >nul
    goto DOCKER_STOPPED
)

echo [ATTENTION] Agent-OS est arrete, mais Docker Desktop n'a pas pu etre ferme automatiquement.
echo Ferme Docker Desktop depuis son icone dans la barre des taches.
goto END_OK

:DOCKER_STOPPED
echo [OK] Docker Desktop est ferme.

:END_OK
echo.
echo Agent-OS V11 et Docker sont arretes.
echo Cette fenetre va se fermer automatiquement.
timeout /t 3 /nobreak >nul
exit /b 0

:DOCKER_NOT_FOUND
echo [INFO] La commande Docker est introuvable.
echo Si Docker Desktop est encore ouvert, ferme-le depuis son icone dans la barre des taches.
goto ERROR_END

:ERROR_END
echo.
pause
exit /b 1
