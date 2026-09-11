@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Diagnostic Agent-OS V11.4
cd /d "%~dp0"

set "A0=%~dp0..\Agent-Zero-V11"
set "PLUGIN=%A0%\usr\plugins\agent_os_memory"
set "GATE=%A0%\usr\extensions\python\_functions\agent\AgentContext\_process_chain\start\_05_agent_os_personal_intake.py"

echo ========================================================
echo       DIAGNOSTIC AGENT-OS V11.4 / PAUL SEMANTIC GATE
 echo ========================================================
echo.

echo --- FICHIERS HOTE ---
if exist "%PLUGIN%\plugin.yaml" (
    type "%PLUGIN%\plugin.yaml"
) else (
    echo MANQUANT : %PLUGIN%\plugin.yaml
)
if exist "%GATE%" (echo [OK] Gate global present) else (echo [ERREUR] Gate global MANQUANT)

echo.
echo --- DOCKER ---
where docker >nul 2>&1 || (echo Docker introuvable & goto LOG)
docker info >nul 2>&1 || (echo Docker ne repond pas & goto LOG)
docker inspect agent-os-v11 >nul 2>&1 || (echo Conteneur agent-os-v11 introuvable & goto LOG)

docker exec agent-os-v11 sh -lc "echo '--- plugin ---'; grep -E '^(version|always_enabled):' /a0/usr/plugins/agent_os_memory/plugin.yaml 2>/dev/null || true; echo '--- gate ---'; ls -l /a0/usr/extensions/python/_functions/agent/AgentContext/_process_chain/start/_05_agent_os_personal_intake.py 2>/dev/null || true; echo '--- paul marker ---'; grep -n 'PAUL_IDENTITY_GUARD_V11_4' /a0/usr/plugins/agent_os_memory/agents/paul/prompts/agent.system.main.specifics.md 2>/dev/null || true"

echo.
echo --- DISCOVERY PYTHON REELLE ---
docker exec agent-os-v11 /opt/venv-a0/bin/python -c "from helpers import subagents,extension,plugins; point='_functions/agent/AgentContext/_process_chain/start'; print('enabled_plugins=',plugins.get_enabled_plugins(None)); print('paths=',subagents.get_paths(None,'extensions/python',*point.split('/'))); print('classes=',[c.__name__ for c in extension._get_extension_classes(point,agent=None)])"

echo.
echo --- IMPORT INTAKE ---
docker exec agent-os-v11 /opt/venv-a0/bin/python -c "from usr.plugins.agent_os_memory.helpers import intake; print('intake=', intake.__file__); print('router=', bool(getattr(intake,'ROUTER_SYSTEM',None))); print('capture=', bool(getattr(intake,'CAPTURE_SYSTEM',None)))"

:LOG
echo.
echo --- 30 DERNIERES LIGNES DU LOG INTAKE ---
if exist "%A0%\usr\agent_os_memory\intake_runtime.log" (
    powershell -NoProfile -Command "Get-Content -Path '%A0%\usr\agent_os_memory\intake_runtime.log' -Tail 30"
) else (
    echo Aucun intake_runtime.log pour l'instant.
)

echo.
echo Copie-moi tout ce qui est affiche dans cette fenetre si Paul se comporte encore mal.
echo.
pause
