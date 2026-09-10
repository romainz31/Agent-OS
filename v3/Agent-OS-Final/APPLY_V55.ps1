$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Runtime = Join-Path $Root "agentos\autonomous_runtime.py"

Write-Host "=== Agent-OS V5.5 ==="
Write-Host "Dossier : $Root"

if (-not (Test-Path $Runtime)) {
    throw "agentos\autonomous_runtime.py introuvable. Exécute ce script depuis v3\Agent-OS-Final."
}

# Le ZIP remplace déjà les fichiers V5.5. On met seulement à jour le numéro
# exposé par AutonomousRuntime sans réécrire tout ce gros fichier.
$Text = [System.IO.File]::ReadAllText($Runtime)
$Text = $Text.Replace("V5.4.1", "V5.5")
$Text = $Text.Replace('VERSION = "5.4.1"', 'VERSION = "5.5"')
[System.IO.File]::WriteAllText(
    $Runtime,
    $Text,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "[1/2] Dépendances..."
python -m pip install -r (Join-Path $Root "requirements.txt")

Write-Host "[2/2] Tests V5.5..."
python (Join-Path $Root "test_v55.py")

Write-Host ""
Write-Host "V5.5 installée. Redémarre api_server.py et telegram_client.py."
