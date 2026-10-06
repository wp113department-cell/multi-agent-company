# Multi Agentic Company: one-click start for Windows.
# Starts PostgreSQL (pgvector), Redis, database migrations, the API and the
# web UI in Docker, then opens http://localhost:3000.
# Requirements: Windows 10/11 with Docker Desktop (installed automatically
# through winget if missing). Nothing else is needed on the PC.

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Host.UI.RawUI.WindowTitle = "Multi Agentic Company"

function Say($msg, $color = "White") { Write-Host "  $msg" -ForegroundColor $color }
function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor DarkYellow }

Write-Host ""
Write-Host "  ==============================================" -ForegroundColor DarkYellow
Write-Host "        MULTI AGENTIC COMPANY  -  starting       " -ForegroundColor DarkYellow
Write-Host "  ==============================================" -ForegroundColor DarkYellow

# ---------------------------------------------------------------- 1. Docker
Step "Checking Docker Desktop"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Say "Docker Desktop is not installed." Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Say "Installing Docker Desktop with winget (this takes a few minutes)..." Yellow
        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        Say ""
        Say "Docker Desktop was installed. Please RESTART Windows, open Docker Desktop" Green
        Say "once (accept its terms), then double-click this start file again." Green
    } else {
        Say "Please install Docker Desktop from https://www.docker.com/products/docker-desktop/" Red
        Say "then double-click this start file again." Red
    }
    Read-Host "Press Enter to close"
    exit 1
}

function Test-DockerUp { docker info *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Test-DockerUp)) {
    Say "Docker Desktop is not running - starting it..." Yellow
    $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Start-Process $dd | Out-Null }
    $waited = 0
    while (-not (Test-DockerUp)) {
        if ($waited -ge 240) {
            Say "Docker Desktop did not start within 4 minutes. Open it manually, wait until it says 'Engine running', then run this file again." Red
            Read-Host "Press Enter to close"
            exit 1
        }
        Start-Sleep -Seconds 5; $waited += 5
        Write-Host "." -NoNewline
    }
    Write-Host ""
}
Say "Docker is running." Green

# ---------------------------------------------------------------- 2. .env
# The app's settings live in backend\.env (API keys, JWT secret, admin
# password). docker compose reads it for every service, and it is also used
# for the ${...} values in docker-compose.yml.
Step "Preparing settings (backend\.env)"
$backendEnv = Join-Path $Root "backend\.env"
if (-not (Test-Path $backendEnv)) {
    $rootEnv = Join-Path $Root ".env"
    if (Test-Path $rootEnv) {
        Copy-Item $rootEnv $backendEnv
        Say "Copied .env to backend\.env" Green
    } else {
        Copy-Item (Join-Path $Root "backend\.env.example") $backendEnv
        Say "Created backend\.env from the example - put your API keys in it for AI features." Yellow
    }
} else {
    Say "backend\.env found." Green
}
$ComposeArgs = @("--env-file", $backendEnv, "--profile", "frontend")

# ---------------------------------------------------------------- 3. Start
Step "Building and starting the services (first run takes 5-15 minutes)"
Say "PostgreSQL + pgvector, Redis, migrations, API, web UI"
docker compose @ComposeArgs up -d --build
if ($LASTEXITCODE -ne 0) {
    Say "Starting the services failed - see the messages above." Red
    Say "Tip: make sure ports 3000, 5432, 6379 and 8000 are free (close other databases/servers)." Yellow
    Read-Host "Press Enter to close"
    exit 1
}

# ---------------------------------------------------------------- 4. Wait
Step "Waiting for the web UI on http://localhost:3000"
$ok = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:3000/login" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 4
    Write-Host "." -NoNewline
}
Write-Host ""
if (-not $ok) {
    Say "The UI is not answering yet. Showing service status:" Yellow
    docker compose @ComposeArgs ps
    Say "Run 'docker compose logs backend frontend' to see details." Yellow
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host ""
Say "Multi Agentic Company is running!" Green
Say "Open:      http://localhost:3000" Green
Say "Sign in:   admin  /  DEFAULT_ADMIN_PASSWORD from backend\.env (default: gridiron123)" Green
 Say "           On first sign-in you choose a new password." Green
Say "Stop it:   double-click Stop-Multi-Agentic-Company.bat" Green
Start-Process "http://localhost:3000"
Write-Host ""
Read-Host "Press Enter to close this window (the app keeps running)"
