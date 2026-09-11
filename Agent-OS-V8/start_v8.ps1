$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".venv\Scripts\python.exe") {
    & .\.venv\Scripts\python.exe -u .\api_server.py
} else {
    python -u .\api_server.py
}
