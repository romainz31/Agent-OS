param(
    [string]$InstallPath = "",
    [switch]$SkipClone
)

$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Upstream = Get-Content (Join-Path $SourceRoot "UPSTREAM.json") -Raw | ConvertFrom-Json

if (-not $InstallPath) {
    $InstallPath = Join-Path (Split-Path -Parent $SourceRoot) "Agent-Zero-V11"
}

if (-not $SkipClone) {
    if (Test-Path $InstallPath) {
        if (-not (Test-Path (Join-Path $InstallPath ".git"))) {
            throw "Le dossier existe mais n'est pas un depot Git : $InstallPath"
        }
    } else {
        git clone $Upstream.repository $InstallPath
        if ($LASTEXITCODE -ne 0) { throw "Echec du clonage Agent Zero." }
    }

    if ($Upstream.commit -and $Upstream.commit -ne "__AGENT_ZERO_COMMIT__") {
        git -C $InstallPath fetch origin $Upstream.commit
        if ($LASTEXITCODE -ne 0) { throw "Echec du telechargement de la version Agent Zero demandee." }
        git -C $InstallPath checkout $Upstream.commit
        if ($LASTEXITCODE -ne 0) { throw "Echec du verrouillage de la version Agent Zero." }
    }
}

if (-not (Test-Path $InstallPath)) {
    throw "Installation Agent Zero introuvable : $InstallPath"
}

$PluginSource = Join-Path $SourceRoot "overlay\usr\plugins\agent_os_memory"
$PluginTarget = Join-Path $InstallPath "usr\plugins\agent_os_memory"
New-Item -ItemType Directory -Force -Path $PluginTarget | Out-Null
Copy-Item -Path (Join-Path $PluginSource "*") -Destination $PluginTarget -Recurse -Force

$DataTarget = Join-Path $InstallPath "usr\agent_os_memory"
New-Item -ItemType Directory -Force -Path $DataTarget | Out-Null

Write-Host "Agent-OS V11 est pret dans : $InstallPath" -ForegroundColor Green
Write-Host "Plugin installe dans : $PluginTarget"
Write-Host "Les donnees seront conservees dans : $DataTarget"
Write-Host "Lance ensuite Agent Zero avec sa procedure Docker habituelle."
