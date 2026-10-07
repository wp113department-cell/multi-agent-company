# Run with Windows PowerShell 5.1 or PowerShell 7; no Docker or API calls.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "settings.ps1")
$testDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mac-login-test-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $testDir | Out-Null
function Assert($condition, $message) {
    if (-not $condition) { throw $message }
}
try {
    $envPath = Join-Path $testDir ".env"
    $example = Join-Path $PSScriptRoot "..\..\backend\.env.example"
    Copy-Item $example $envPath
    Initialize-WebLoginSettings $envPath
    $first = [System.IO.File]::ReadAllText($envPath)
    $key = [regex]::Match($first, '(?m)^JWT_SECRET_KEY=([^\r\n]+)').Groups[1].Value
    Assert ($key.Length -ge 32) "First run must generate a signing key."
    Assert ($first -match '(?m)^JWT_AUTH_ENABLED=true\r?$') "First run must enable cookie authentication."
    Initialize-WebLoginSettings $envPath
    Assert ([System.IO.File]::ReadAllText($envPath) -eq $first) "Restart must preserve the signing key and configuration."

    $existingKey = 'existing-key-' + ('a' * 40)
    [System.IO.File]::WriteAllText($envPath, "JWT_SECRET_KEY='$existingKey' # keep`nJWT_AUTH_ENABLED=false`nCUSTOM_VALUE=unchanged`n")
    Initialize-WebLoginSettings $envPath
    $existing = [System.IO.File]::ReadAllText($envPath)
    Assert ($existing.Contains("JWT_SECRET_KEY='$existingKey' # keep")) "Existing key must stay unchanged."
    Assert ($existing.Contains('CUSTOM_VALUE=unchanged')) "Other settings must stay unchanged."

    [System.IO.File]::WriteAllText($envPath, "export jwt_secret_key='$existingKey'`nexport jwt_auth_enabled=false`n")
    Initialize-WebLoginSettings $envPath
    $exported = [System.IO.File]::ReadAllText($envPath)
    Assert ($exported.Contains("export jwt_secret_key='$existingKey'")) "Exported existing keys must stay unchanged."
    Assert ($exported -match '(?m)^JWT_AUTH_ENABLED=true\r?$') "Exported authentication flags must be enabled."

    $hashKey = ('a' * 20) + '#' + ('b' * 20)
    [System.IO.File]::WriteAllText($envPath, "JWT_SECRET_KEY=$hashKey # keep`nJWT_AUTH_ENABLED=false`n")
    Initialize-WebLoginSettings $envPath
    Assert ([System.IO.File]::ReadAllText($envPath).Contains("JWT_SECRET_KEY=$hashKey # keep")) "Hash characters inside existing keys must stay unchanged."

    [System.IO.File]::WriteAllText($envPath, "JWT_SECRET_KEY=`"`" # empty`nJWT_AUTH_ENABLED=false`n")
    Initialize-WebLoginSettings $envPath
    Assert ([System.IO.File]::ReadAllText($envPath) -match '(?m)^JWT_SECRET_KEY=.{32,}') "Quoted empty keys must be initialized."

    [System.IO.File]::WriteAllText($envPath, "CUSTOM_VALUE=unchanged`n")
    Initialize-WebLoginSettings $envPath
    Assert ([System.IO.File]::ReadAllText($envPath) -match '(?m)^JWT_AUTH_ENABLED=true\r?$') "Missing JWT settings must be added."

    [System.IO.File]::WriteAllText($envPath, "JWT_SECRET_KEY=short`nJWT_AUTH_ENABLED=false`n")
    $failed = $false
    try { Initialize-WebLoginSettings $envPath } catch { $failed = $true }
    Assert $failed "Invalid existing keys must fail with an actionable error."
    Assert ([System.IO.File]::ReadAllText($envPath).Contains('JWT_SECRET_KEY=short')) "Invalid existing keys must not be silently replaced."
    Write-Host "Windows browser-login settings: all checks passed."
} finally {
    Remove-Item -Recurse -Force $testDir
}
