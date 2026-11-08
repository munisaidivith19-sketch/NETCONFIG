# Starts the backend in development mode with auto-reload.
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1
$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "..\backend" | Resolve-Path
Set-Location "$backend"

$venvPython = Join-Path "$backend" ".venv\Scripts\python.exe"
if (-not (Test-Path "$venvPython")) {
    # Python 3.12 is the target; 3.10 is accepted until 3.12 is installed.
    $created = $false
    foreach ($version in @("-3.12", "-3.10")) {
        & py $version -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Creating .venv with Python $version"
            & py $version -m venv .venv
            $created = $true
            break
        }
    }
    if (-not $created) { throw "Python 3.12 (or 3.10) not found. Install it from python.org." }
}

& "$venvPython" -m pip install --disable-pip-version-check -q -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created backend\.env from .env.example" }

& "$venvPython" -m app --reload
