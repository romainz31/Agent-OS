@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Diagnostic Agent-OS V11.8
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"
echo ========================================================
echo       DIAGNOSTIC AGENT-OS V11.8
echo ========================================================
if exist "%PLUGIN%\plugin.yaml" type "%PLUGIN%\plugin.yaml"
where docker >nul 2>&1 || goto LOG
docker info >nul 2>&1 || goto LOG
docker inspect agent-os-v11 >nul 2>&1 || goto LOG
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; print('intake=',intake.__file__); print('resolver=',hasattr(intake,'RESOLVER_SYSTEM')); print('isolated=', 'current_turn_only' in open(intake.__file__,encoding='utf-8').read())"
:LOG
echo.
echo --- 80 DERNIERES LIGNES INTAKE ---
if exist "%A0%\usr\agent_os_memory\intake_runtime.log" (
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Path '%A0%\usr\agent_os_memory\intake_runtime.log' -Tail 80"
) else (
  echo Aucun log.
)
echo.
echo Attendu :
echo   _pipeline_diagnostic.primary_scope = current_turn_only
echo   query_follow_up_allowed = false pour une question autonome
echo   resolver_used = true seulement pour ma copine / elle / l'
pause
