# Shared by the scripts in this folder (dot-sourced: . "$PSScriptRoot\_common.ps1").
# Project paths, the backend .venv check and backend\.env.

$Root = Join-Path $PSScriptRoot ".." | Resolve-Path
$Backend = Join-Path "$Root" "backend"
$Frontend = Join-Path "$Root" "frontend"
$Py = Join-Path "$Backend" ".venv\Scripts\python.exe"

function Assert-Venv {
    if (-not (Test-Path "$Py")) {
        Write-Host "backend\.venv not found: run scripts\dev-backend.ps1 once first." -ForegroundColor Red
        exit 1
    }
}

function Initialize-EnvFile {
    $envFile = Join-Path "$Backend" ".env"
    if (-not (Test-Path "$envFile")) {
        Copy-Item (Join-Path "$Backend" ".env.example") "$envFile"
        Write-Host "Created backend\.env from .env.example"
    }
}
