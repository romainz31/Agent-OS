@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Agent-OS V12 - Demarrage

set "CONTAINER=agent-os-v12"
set "URL=http://localhost:5080"
set "DOCKER_DESKTOP_1=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "DOCKER_DESKTOP_2=%LOCALAPPDATA%\Docker\Docker Desktop.exe"

echo.
echo ==========================================
echo          AGENT-OS V12 + AGENT ZERO
echo ==========================================
echo.

where docker >nul 2>&1
if errorlevel 1 goto DOCKER_NOT_FOUND

docker info >nul 2>&1
if not errorlevel 1 goto DOCKER_READY

echo [INFO] Docker n'est pas encore pret.
echo [INFO] Tentative de demarrage de Docker Desktop...

if exist "%DOCKER_DESKTOP_1%" (
    start "" "%DOCKER_DESKTOP_1%"
    goto WAIT_DOCKER_INIT
)

if exist "%DOCKER_DESKTOP_2%" (
    start "" "%DOCKER_DESKTOP_2%"
    goto WAIT_DOCKER_INIT
)

goto DOCKER_DESKTOP_NOT_FOUND

:WAIT_DOCKER_INIT
echo [INFO] Attente du moteur Docker...
set /a tries=0

:WAIT_DOCKER
docker info >nul 2>&1
if not errorlevel 1 goto DOCKER_READY

set /a tries+=1
if !tries! GEQ 60 goto DOCKER_TIMEOUT

timeout /t 2 /nobreak >nul
goto WAIT_DOCKER

:DOCKER_READY
echo [OK] Docker est pret.

docker inspect "%CONTAINER%" >nul 2>&1
if errorlevel 1 goto CONTAINER_NOT_FOUND

set "RUNNING="
for /f "delims=" %%S in ('docker inspect -f "{{.State.Running}}" "%CONTAINER%" 2^>nul') do set "RUNNING=%%S"

if /I "!RUNNING!"=="true" (
    echo [OK] Agent-OS est deja demarre.
    goto CONTAINER_READY
)

echo [INFO] Demarrage d'Agent-OS...
docker start "%CONTAINER%" >nul 2>&1
if errorlevel 1 goto CONTAINER_START_ERROR

echo [OK] Conteneur Agent-OS demarre.

:CONTAINER_READY
echo [INFO] Verification du plugin Agent-OS V12...
docker exec "%CONTAINER%" test -f /a0/usr/plugins/agent_os_memory/plugin.yaml >nul 2>&1
if errorlevel 1 (
    echo [ATTENTION] Le conteneur tourne, mais le plugin agent_os_memory n'a pas ete trouve.
) else (
    echo [OK] Plugin Agent-OS V12 detecte.
)

echo [INFO] Attente de l'interface Web...
set /a webtries=0

:WAIT_WEB
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto OPEN_WEB

set /a webtries+=1
if !webtries! GEQ 30 goto OPEN_WEB_WITH_WARNING

timeout /t 1 /nobreak >nul
goto WAIT_WEB

:OPEN_WEB
echo [OK] Interface Web disponible.
goto BROWSER

:OPEN_WEB_WITH_WARNING
echo [ATTENTION] L'interface met plus de temps que prevu a repondre.
echo [INFO] Ouverture du navigateur quand meme.

:BROWSER
start "" "%URL%"
echo.
echo Agent-OS V12 est lance.
echo Cette fenetre va se fermer automatiquement.
timeout /t 3 /nobreak >nul
exit /b 0

:DOCKER_NOT_FOUND
echo [ERREUR] La commande Docker est introuvable.
echo Installe Docker Desktop ou verifie son installation.
goto ERROR_END

:DOCKER_DESKTOP_NOT_FOUND
echo [ERREUR] Docker Desktop n'a pas ete trouve automatiquement.
echo Demarre Docker Desktop manuellement puis relance ce fichier.
goto ERROR_END

:DOCKER_TIMEOUT
echo [ERREUR] Docker Desktop a ete lance mais son moteur n'est toujours pas pret.
echo Verifie Docker Desktop puis relance Agent-OS.
goto ERROR_END

:CONTAINER_NOT_FOUND
echo [ERREUR] Le conteneur "%CONTAINER%" n'existe pas.
echo Le lanceur ne recree pas automatiquement l'installation.
echo Relance l'installation/configuration Docker de la V12 une premiere fois.
goto ERROR_END

:CONTAINER_START_ERROR
echo [ERREUR] Impossible de demarrer "%CONTAINER%".
echo.
echo Derniers logs :
docker logs --tail 30 "%CONTAINER%"
goto ERROR_END

:ERROR_END
echo.
pause
exit /b 1
