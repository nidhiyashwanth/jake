[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

& git -C $repoRoot check-ignore -q -- .env
if ($LASTEXITCODE -ne 0) {
    Write-Output "SECRET CHECK FAILED: .env is not ignored by Git."
    exit 1
}

$trackedFiles = @(git -C $repoRoot ls-files)
$forbiddenPatterns = @(
    'postgresql\+psycopg://[^:$<>\s]+:(mvp|password|secret|changeme|change-me)@',
    'POSTGRES_PASSWORD=(mvp|password|secret|changeme|change-me)(\s|$)',
    '-----BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY-----'
)

$matches = @()
foreach ($relativePath in $trackedFiles) {
    if ([string]::IsNullOrWhiteSpace($relativePath) -or $relativePath -eq '.env.example' -or $relativePath -eq 'scripts/check-secrets.ps1') {
        continue
    }
    $absolutePath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
        continue
    }
    $content = Get-Content -Raw -LiteralPath $absolutePath
    foreach ($pattern in $forbiddenPatterns) {
        if ($content -match $pattern) {
            $matches += $relativePath
            break
        }
    }
}

if ($matches.Count -gt 0) {
    Write-Output "SECRET CHECK FAILED: secret-like defaults detected in tracked paths: $($matches -join ', ')"
    exit 1
}

Write-Output "SECRET CHECK PASS: .env is ignored and tracked files contain no banned credential defaults."
exit 0
