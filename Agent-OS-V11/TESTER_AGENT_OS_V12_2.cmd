@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0overlay\usr\plugins"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m unittest tests.test_semantic_intake -v
) else (
  python -m unittest tests.test_semantic_intake -v
)
pause
