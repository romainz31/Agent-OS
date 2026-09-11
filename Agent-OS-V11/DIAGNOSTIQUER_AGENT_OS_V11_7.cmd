@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Diagnostic Agent-OS V11.7
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"

echo ========================================================
echo        DIAGNOSTIC AGENT-OS V11.7
echo ========================================================
echo.
if exist "%PLUGIN%\plugin.yaml" type "%PLUGIN%\plugin.yaml"
echo.
where docker >nul 2>&1 || goto LOG
docker info >nul 2>&1 || goto LOG
docker inspect agent-os-v11 >nul 2>&1 || goto LOG
echo --- RUNTIME ---
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; print('intake=',intake.__file__); print('uses_pending=', 'uses_pending' in intake.ROUTER_SYSTEM); print('middle_name=', 'middle_name' in intake.CAPTURE_SYSTEM)"
:LOG
echo.
echo --- 60 DERNIERES LIGNES INTAKE ---
if exist "%A0%\usr\agent_os_memory\intake_runtime.log" (
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Path '%A0%\usr\agent_os_memory\intake_runtime.log' -Tail 60"
) else (
  echo Aucun log.
)
echo.
pause
