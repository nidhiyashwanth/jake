[CmdletBinding()]
param(
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$featurePath = Join-Path $repoRoot "feature-list.json"

function Invoke-RepositoryScript {
    param([Parameter(Mandatory)][string]$RelativePath)

    $scriptPath = Join-Path $repoRoot $RelativePath
    & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "$RelativePath failed. Repair its first reported failure before retrying the complete-product gate."
    }
}

if (-not (Test-Path -LiteralPath $featurePath -PathType Leaf)) {
    throw "feature-list.json is missing. The complete-product gate needs the executable task state."
}

$featureList = Get-Content -Raw -LiteralPath $featurePath | ConvertFrom-Json
$foundationIds = @("H01", "H02", "H03")
$requiredFeatures = @($featureList.features | Where-Object { $_.id -notin $foundationIds })
$openFeatures = @($requiredFeatures | Where-Object { $_.state -ne "passing" })

if ($openFeatures.Count -gt 0) {
    Write-Output "PRODUCT GATE BLOCKED: $($openFeatures.Count) required work package(s) remain open."
    foreach ($feature in $openFeatures) {
        Write-Output "- $($feature.id): $($feature.state)"
    }
    Write-Output "Repair: complete each package in task.md and attach executable evidence before rerunning this gate."
    exit 1
}

Invoke-RepositoryScript -RelativePath "scripts/verify-harness.ps1"
Invoke-RepositoryScript -RelativePath "scripts/check-secrets.ps1"
Invoke-RepositoryScript -RelativePath "scripts/verify-mvp.ps1"
Invoke-RepositoryScript -RelativePath "scripts/verify-launch.ps1"

& git -C $repoRoot diff --check
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check failed. Repair whitespace errors before release."
}

if (-not $AllowDirty) {
    $dirty = @(git -C $repoRoot status --porcelain)
    if ($dirty.Count -gt 0) {
        throw "PRODUCT GATE BLOCKED: working tree is dirty. Commit or remove the listed generated changes before release."
    }
}

Write-Output "PRODUCT GATE PASS: all required work packages, harness checks, secret checks, F01 runtime checks, and repository checks passed."
exit 0
