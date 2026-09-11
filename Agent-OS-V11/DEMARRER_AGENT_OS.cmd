@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Agent-OS V11 - Demarrage complet

set "CONTAINER=agent-os-v11"
set "URL=http://localhost:5080"

set "DOCKER_DESKTOP_1=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "DOCKER_DESKTOP_2=%LOCALAPPDATA%\Docker\Docker Desktop.exe"

echo.
echo ==========================================
echo      AGENT-OS V11 - DEMARRAGE COMPLET
echo ==========================================
echo.

rem =========================================================
rem 1. Verifier que Docker est installe
rem =========================================================
where docker >nul 2>&1
if errorlevel 1 goto DOCKER_NOT_FOUND

rem =========================================================
rem 2. Demarrer Docker Desktop si le moteur Docker ne repond pas
rem =========================================================
docker info >nul 2>&1
if not errorlevel 1 goto DOCKER_READY

echo [INFO] Docker n'est pas demarre.
echo [INFO] Demarrage de Docker Desktop...

rem Methode moderne si disponible
docker desktop start >nul 2>&1
if not errorlevel 1 goto WAIT_DOCKER_INIT

rem Sinon lancement direct de Docker Desktop
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
if !tries! GEQ 90 goto DOCKER_TIMEOUT

timeout /t 2 /nobreak >nul
goto WAIT_DOCKER

:DOCKER_READY
echo [OK] Docker est pret.

rem =========================================================
rem 3. Verifier que le conteneur Agent-OS existe
rem =========================================================
docker inspect "%CONTAINER%" >nul 2>&1
if errorlevel 1 goto CONTAINER_NOT_FOUND

rem =========================================================
rem 4. Demarrer Agent-OS si necessaire
rem =========================================================
set "RUNNING="
for /f "delims=" %%S in ('docker inspect -f "{{.State.Running}}" "%CONTAINER%" 2^>nul') do set "RUNNING=%%S"

if /I "!RUNNING!"=="true" (
    echo [OK] Agent-OS est deja demarre.
    goto WAIT_WEB_INIT
)

echo [INFO] Demarrage du conteneur Agent-OS...
docker start "%CONTAINER%" >nul 2>&1
if errorlevel 1 goto CONTAINER_START_ERROR

echo [OK] Agent-OS est demarre.

rem =========================================================
rem 5. Attendre que l'interface Web reponde
rem =========================================================
:WAIT_WEB_INIT
echo [INFO] Attente de l'interface Web...
set /a webtries=0

:WAIT_WEB
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } } catch {}; exit 1" >nul 2>&1

if not errorlevel 1 goto OPEN_WEB

set /a webtries+=1
if !webtries! GEQ 60 goto OPEN_WEB_WARNING

timeout /t 1 /nobreak >nul
goto WAIT_WEB

:OPEN_WEB
echo [OK] Interface Agent-OS disponible.
goto BROWSER

:OPEN_WEB_WARNING
echo [ATTENTION] L'interface Web ne repond pas encore.
echo [INFO] Le navigateur va quand meme etre ouvert.

:BROWSER
start "" "%URL%"

echo.
echo ==========================================
echo     AGENT-OS V11 EST LANCE
echo ==========================================
echo.
echo Docker Desktop : demarre
echo Agent-OS       : demarre
echo Interface      : %URL%
echo.
timeout /t 3 /nobreak >nul
exit /b 0


:DOCKER_NOT_FOUND
echo [ERREUR] La commande Docker est introuvable.
echo Installe Docker Desktop ou verifie son installation.
goto ERROR_END

:DOCKER_DESKTOP_NOT_FOUND
echo [ERREUR] Docker Desktop n'a pas ete trouve automatiquement.
echo Emplacements testes :
echo   %DOCKER_DESKTOP_1%
echo   %DOCKER_DESKTOP_2%
goto ERROR_END

:DOCKER_TIMEOUT
echo [ERREUR] Docker Desktop a ete lance mais le moteur Docker
echo ne repond toujours pas.
echo Ouvre Docker Desktop pour verifier son etat.
goto ERROR_END

:CONTAINER_NOT_FOUND
echo [ERREUR] Le conteneur "%CONTAINER%" n'existe pas.
echo Il faut d'abord creer/configurer Agent-OS V11.
goto ERROR_END

:CONTAINER_START_ERROR
echo [ERREUR] Impossible de demarrer "%CONTAINER%".
echo.
echo Derniers logs du conteneur :
docker logs --tail 30 "%CONTAINER%"
goto ERROR_END

:ERROR_END
echo.
pause
exit /b 1
