# Multi Agentic Company: stop all services (data is kept in Docker volumes).
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
Write-Host "Stopping Multi Agentic Company..." -ForegroundColor DarkYellow
$ErrorActionPreference = "Continue"
if (Test-Path "backend\.env") {
    cmd /c "docker compose --env-file backend\.env --profile frontend down 2>&1"
} else {
    cmd /c "docker compose --profile frontend down 2>&1"
}
Write-Host "Stopped. Your data is kept; run Start-Multi-Agentic-Company.bat to start again." -ForegroundColor Green
Read-Host "Press Enter to close"
