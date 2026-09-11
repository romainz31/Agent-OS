@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Diagnostic Agent-OS V12.2
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"
echo ========================================================
echo       DIAGNOSTIC AGENT-OS V12.2
echo ========================================================
if exist "%PLUGIN%\plugin.yaml" type "%PLUGIN%\plugin.yaml"
where docker >nul 2>&1 || goto LOG
docker info >nul 2>&1 || goto LOG
docker inspect agent-os-v11 >nul 2>&1 || goto LOG
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; print('intake=',intake.__file__); print('auditor=',hasattr(intake,'REFERENCE_AUDITOR_SYSTEM')); print('targeted=',hasattr(intake,'TARGETED_CLARIFICATION_SYSTEM'))"
:LOG
echo.
echo --- 120 DERNIERES LIGNES INTAKE ---
if exist "%A0%\usr\agent_os_memory\intake_runtime.log" (
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Path '%A0%\usr\agent_os_memory\intake_runtime.log' -Tail 120"
) else (
  echo Aucun log.
)
echo.
echo A verifier :
echo - _reference_audit.used
echo - _resolution_diagnostic.remaining
echo - _ambiguity_diagnostic.proposals
echo - _targeted_clarification_raw
echo - pending type reference_clarification
pause
