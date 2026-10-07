# Multi Agentic Company: load or remove the demo data (for client demos).
# Usage: demo.ps1 load | remove
param([string]$Action = "load")
$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root


$running = cmd /c "docker compose --env-file backend\.env ps --status running --services 2>nul"
if (-not ($running -match "backend")) {
    Write-Host "The app is not running. Double-click Start-Multi-Agentic-Company.bat first, then run this again." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

if ($Action -eq "remove") {
    Write-Host "Removing the demo data..." -ForegroundColor DarkYellow
    cmd /c "docker compose --env-file backend\.env exec -T backend python -m scripts.seed_demo_data --remove 2>&1"
} else {
    Write-Host "Loading the demo data (3 projects, tasks in every stage, approvals, suggestions, roadmap)..." -ForegroundColor DarkYellow
    cmd /c "docker compose --env-file backend\.env exec -T backend python -m scripts.seed_demo_data 2>&1"
}
if ($LASTEXITCODE -eq 0) {
    Write-Host "Done. Refresh http://localhost:3000 in your browser." -ForegroundColor Green
} else {
    Write-Host "Something went wrong - see the messages above." -ForegroundColor Red
}
Read-Host "Press Enter to close"
