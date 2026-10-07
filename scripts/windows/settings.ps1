# Shared first-run configuration; compatible with Windows PowerShell 5.1.
function Initialize-WebLoginSettings([string]$EnvPath) {
    $content = [System.IO.File]::ReadAllText($EnvPath)
    $secretLines = [regex]::Matches($content, '(?im)^[ \t]*(?:export[ \t]+)?JWT_SECRET_KEY[ \t]*=([^\r\n]*)')
    $secret = ""
    if ($secretLines.Count -gt 0) {
        $value = $secretLines[$secretLines.Count - 1].Groups[1].Value.Trim()
        if ($value.StartsWith('"') -or $value.StartsWith("'")) {
            $quote = $value.Substring(0, 1)
            $end = $value.IndexOf($quote, 1)
            if ($end -lt 0) { throw "JWT_SECRET_KEY has an unclosed quote in backend\.env." }
            $secret = $value.Substring(1, $end - 1)
        } else {
            $secret = [regex]::Replace($value, '[ \t]+#.*$', '').Trim()
        }
    }
    if (-not $secret) {
        $bytes = New-Object byte[] 48
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $secret = [Convert]::ToBase64String($bytes)
        if ($secretLines.Count -gt 0) {
            $content = [regex]::Replace($content, '(?im)^[ \t]*(?:export[ \t]+)?JWT_SECRET_KEY[ \t]*=[^\r\n]*', "JWT_SECRET_KEY=$secret")
        } else {
            $content += "`r`nJWT_SECRET_KEY=$secret`r`n"
        }
    } elseif ($secret.Length -lt 32) {
        throw "JWT_SECRET_KEY must contain at least 32 characters. Update backend\.env and start again."
    }
    # The web UI authenticates with a cookie, which RBAC reads in JWT mode.
    if ([regex]::IsMatch($content, '(?im)^[ \t]*(?:export[ \t]+)?JWT_AUTH_ENABLED[ \t]*=')) {
        $content = [regex]::Replace($content, '(?im)^[ \t]*(?:export[ \t]+)?JWT_AUTH_ENABLED[ \t]*=[^\r\n]*', 'JWT_AUTH_ENABLED=true')
    } else {
        $content += "`r`nJWT_AUTH_ENABLED=true`r`n"
    }
    [System.IO.File]::WriteAllText($EnvPath, $content, (New-Object System.Text.UTF8Encoding $false))
}
