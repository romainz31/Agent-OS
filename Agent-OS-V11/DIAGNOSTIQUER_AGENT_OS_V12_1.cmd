@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Diagnostic Agent-OS V12.1
cd /d "%~dp0"
set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"
echo ========================================================
echo       DIAGNOSTIC AGENT-OS V12.1
echo ========================================================
if exist "%PLUGIN%\plugin.yaml" type "%PLUGIN%\plugin.yaml"
where docker >nul 2>&1 || goto LOG
docker info >nul 2>&1 || goto LOG
docker inspect agent-os-v11 >nul 2>&1 || goto LOG
docker exec -w /a0 agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; print('intake=',intake.__file__); print('ambiguity_matcher=',hasattr(intake,'AMBIGUITY_MATCHER_SYSTEM')); print('ambiguity_confirmation=',hasattr(intake,'AMBIGUITY_CONFIRMATION_SYSTEM'))"
:LOG
echo.
echo --- 100 DERNIERES LIGNES INTAKE ---
if exist "%A0%\usr\agent_os_memory\intake_runtime.log" (
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Path '%A0%\usr\agent_os_memory\intake_runtime.log' -Tail 100"
) else (
  echo Aucun log.
)
echo.
echo A verifier :
echo - _ambiguity_diagnostic.used
echo - _ambiguity_diagnostic.proposals
echo - source_text du souvenir propose
echo - _ambiguity_confirmation apres confirmation utilisateur
pause
