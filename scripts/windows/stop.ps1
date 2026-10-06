# Multi Agentic Company: stop all services (data is kept in Docker volumes).
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
Write-Host "Stopping Multi Agentic Company..." -ForegroundColor DarkYellow
$envArgs = @()
if (Test-Path "backend\.env") { $envArgs = @("--env-file", "backend\.env") }
docker compose @envArgs --profile frontend down
Write-Host "Stopped. Your data is kept; run Start-Multi-Agentic-Company.bat to start again." -ForegroundColor Green
Read-Host "Press Enter to close"
