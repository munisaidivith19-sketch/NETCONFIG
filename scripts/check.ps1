# Release checks (CLAUDE.md 8.7 and 9): every test and static check in one command.
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File scripts\check.ps1 [-Quick]
#   -Quick  skips pip-audit and npm audit (they need the internet)
# Exit code 0 only if every check passes. Database tests fail (instead of being skipped) without MongoDB.
param([switch]$Quick)

. "$PSScriptRoot\_common.ps1"
Assert-Venv

# The CVE IDs accepted in docs/ACCEPTED_RISKS.md (its table rows). Only these are ignored, so any new
# vulnerability still fails the check.
$risks = Join-Path "$Root" "docs\ACCEPTED_RISKS.md"
$acceptedVulns = @(Get-Content "$risks" | Where-Object { $_ -like "|*" } |
    Select-String -Pattern "CVE-\d{4}-\d+" -AllMatches | ForEach-Object { $_.Matches.Value } | Sort-Object -Unique)

$results = [ordered]@{}

function Step([string]$name, [string]$dir, [scriptblock]$command) {
    Write-Host ""
    Write-Host "== $name" -ForegroundColor Cyan
    Push-Location "$dir"
    try {
        & $command
        $ok = ($LASTEXITCODE -eq 0)
    } catch {
        Write-Host $_ -ForegroundColor Red
        $ok = $false
    } finally {
        Pop-Location
    }
    $script:results[$name] = $ok
}

$env:REQUIRE_MONGO = "1"  # tests/conftest.py: no MongoDB = failed database tests, not skipped ones
Step "pytest (backend)" "$Backend" { & "$Py" -m pytest -p no:warnings -rs }
Remove-Item Env:REQUIRE_MONGO
Step "ruff" "$Backend" { & "$Py" -m ruff check . }
# Findings go to stdout; stderr only has notes about the wording of "# nosec" comments.
Step "bandit" "$Backend" { & "$Py" -m bandit -q -c pyproject.toml -r app scripts 2>$null }
if (-not $Quick) {
    Step "pip-audit ($($acceptedVulns.Count) accepted IDs ignored)" "$Backend" {
        $ignore = $acceptedVulns | ForEach-Object { "--ignore-vuln"; $_ }
        & "$Py" -m pip_audit -r requirements.txt @ignore
    }
}
Step "vitest (frontend)" "$Frontend" { & npm.cmd test --silent }
Step "vite build" "$Frontend" { & npm.cmd run build --silent }
if (-not $Quick) {
    Step "npm audit" "$Frontend" { & npm.cmd audit }
}

Write-Host ""
Write-Host "== Summary" -ForegroundColor Cyan
$failed = 0
foreach ($name in $results.Keys) {
    if ($results[$name]) { Write-Host ("  PASS  " + $name) -ForegroundColor Green }
    else { Write-Host ("  FAIL  " + $name) -ForegroundColor Red; $failed++ }
}
if ($Quick) { Write-Host "  (pip-audit and npm audit skipped: -Quick)" -ForegroundColor Yellow }
exit $(if ($failed -eq 0) { 0 } else { 1 })
