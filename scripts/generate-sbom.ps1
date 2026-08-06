[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Image,
    [string]$OutputDirectory = "artifacts\supply-chain",
    [switch]$StaticOnly,
    [switch]$AllowScannerAuthFailure
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedOutput = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Supply-chain check failed: $Message" }
}

Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot "docs\DEPLOYMENT.md") -PathType Leaf) "deployment contract is missing"
Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot "backend\requirements.lock") -PathType Leaf) "backend dependency lock is missing"
Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot "frontend\package-lock.json") -PathType Leaf) "frontend npm lock is missing"
if ($StaticOnly) {
    Write-Output "SUPPLY CHAIN STATIC PASS: backend/npm locks and deployment contract are present."
    exit 0
}

$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $docker) { $docker = Get-Command docker -ErrorAction SilentlyContinue }
Assert-Condition ($null -ne $docker) "Docker CLI is required"
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null

$imageConfig = @(& $docker.Source "image" "inspect" $Image "--format" "{{json .Config.Env}}" 2>&1)
if ($LASTEXITCODE -ne 0) { throw "image '$Image' was not found locally" }
$imageConfigText = $imageConfig -join " "
foreach ($forbidden in @("VAULT_KEK_BASE64=", "LANGFUSE_SECRET_KEY=", "SENTRY_DSN=", "POSTGRES_PASSWORD=", "PRIVATE_KEY=", "BEARER_TOKEN=")) {
    Assert-Condition (-not ($imageConfigText -match [regex]::Escape($forbidden))) "image configuration contains a secret-bearing environment key"
}

$safeName = ($Image -replace "[^A-Za-z0-9_.-]", "_")
$sbomPath = Join-Path $resolvedOutput "$safeName.cyclonedx.json"
$cvePath = Join-Path $resolvedOutput "$safeName.cves.sarif"
$previous = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $scout = @(& $docker.Source "scout" "sbom" "--format" "cyclonedx" "--output" $sbomPath "local://$Image" 2>&1)
    $sbomExitCode = $LASTEXITCODE
    $cves = @(& $docker.Source "scout" "cves" "--only-severity" "critical,high" "--format" "sarif" "--output" $cvePath "--exit-code" "local://$Image" 2>&1)
    $cveExitCode = $LASTEXITCODE
} finally { $ErrorActionPreference = $previous }
if ($sbomExitCode -ne 0 -or -not (Test-Path -LiteralPath $sbomPath -PathType Leaf)) { throw "Docker Scout could not produce an SBOM for the local image" }
if ($cveExitCode -ne 0) {
    $cveOutput = $cves -join "`n"
    $requiresLogin = $cveOutput -match "Log in with your Docker ID|docker login"
    if ($AllowScannerAuthFailure -and $requiresLogin) {
        $unavailablePath = Join-Path $resolvedOutput "$safeName.cves-unavailable.txt"
        "Docker Scout CVE reporting requires Docker authentication on this runner. CI Trivy is the authoritative image-vulnerability gate." | Set-Content -LiteralPath $unavailablePath -Encoding utf8
        Write-Output "SUPPLY CHAIN PARTIAL: SBOM generated for $Image; Docker Scout CVE reporting requires login. CI Trivy remains required."
    } else {
        throw "Docker Scout found critical/high image vulnerabilities or failed before producing a report; inspect the ignored SARIF artifact under artifacts/supply-chain"
    }
} else {
    Write-Output "SUPPLY CHAIN PASS: SBOM and critical/high CVE report generated for $Image."
}
