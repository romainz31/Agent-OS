param([switch]$Integrations)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.14 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if ($Integrations) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements-integrations.txt
}

Write-Host "Installation terminée."
Write-Host "Tests : .\.venv\Scripts\python.exe -m tests.test_v8"
Write-Host "Serveur : .\.venv\Scripts\python.exe -u .\api_server.py"
