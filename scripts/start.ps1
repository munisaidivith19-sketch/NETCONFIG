# Starts NetConfig Studio for daily use: one process, production mode.
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 [-NoBrowser]
# First time: run scripts\dev-backend.ps1 once (creates backend\.venv and backend\.env) and npm ci in frontend\.
param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_common.ps1"

function Fail([string]$message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Test-Port([string]$hostName, [int]$port) {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect($hostName, $port); return $true } catch { return $false } finally { $client.Close() }
}

# 1. Backend environment
Assert-Venv
Initialize-EnvFile

# 2. MongoDB (local Windows service). The app waits for it, but jobs cannot run until it is up.
if (Test-Port "127.0.0.1" 27017) {
    Write-Host "MongoDB is reachable on 127.0.0.1:27017."
} else {
    Write-Host "MongoDB is not reachable on 127.0.0.1:27017 yet; the app will keep retrying. Start the MongoDB" `
        "service (Services app, or an admin PowerShell: Start-Service MongoDB)." -ForegroundColor Yellow
}

# 3. Frontend build: rebuilt when dist is missing or older than any source file.
$index = Join-Path "$Frontend" "dist\index.html"
$sources = @(Get-ChildItem -Path (Join-Path "$Frontend" "src") -Recurse -File) +
           @(Get-ChildItem -Path (Join-Path "$Frontend" "*") -File -Include "index.html", "package-lock.json", "vite.config.js")
$newest = ($sources | Measure-Object -Property LastWriteTime -Maximum).Maximum
if (-not (Test-Path "$index") -or (Get-Item "$index").LastWriteTime -lt $newest) {
    Write-Host "Building the frontend..."
    Push-Location "$Frontend"
    try {
        if (-not (Test-Path "node_modules")) { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { Fail "npm ci failed." } }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { Fail "The frontend build failed." }
    } finally {
        Pop-Location
    }
}

# 4. Start. ENV=production: API docs off, simulation refused, no dev origin. Everything else comes from
#    backend\.env, read by the app's own Settings (so the address and http/https here always match it).
$env:ENV = "production"
$env:SIMULATE_DEVICES = "false"  # beats a SIMULATE_DEVICES=true left in backend\.env
Set-Location "$Backend"
$where = & "$Py" -c "from app.config import Settings; s = Settings(); print(s.host, s.port, 'https' if s.https else 'http')"
if ($LASTEXITCODE -ne 0) { Fail "backend\.env could not be read (see the error above)." }
$appHost, $appPort, $scheme = "$where".Split(" ")
$urlHost = if ($appHost -eq "::1") { "[::1]" } else { $appHost }
$url = "${scheme}://${urlHost}:${appPort}/"
if (-not $NoBrowser) {
    # Opens the browser once the port answers (checked for up to 60 s), without blocking the server.
    Start-Job -ScriptBlock {
        param($h, $p, $u)
        for ($i = 0; $i -lt 60; $i++) {
            $c = New-Object Net.Sockets.TcpClient
            try { $c.Connect($h, [int]$p); Start-Process $u; return } catch { Start-Sleep -Seconds 1 } finally { $c.Close() }
        }
    } -ArgumentList $appHost, $appPort, $url | Out-Null
}
Write-Host "NetConfig Studio: $url  (Ctrl+C to stop)" -ForegroundColor Green
& "$Py" -m app
