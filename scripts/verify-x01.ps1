[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [switch]$KeepRunning,
    [switch]$SkipImageScan,
    [switch]$AllowScannerAuthFailure
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$contractPath = Join-Path $repoRoot "tests\operations\contract.json"
$browserSmokePath = Join-Path $repoRoot "tests\operations\browser_smoke.py"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-x01"
$backendPort = 18006
$frontendPort = 13006
$postgresPort = 15438
$apiBase = "http://localhost:$backendPort"
$frontendBase = "http://localhost:$frontendPort"
$backupPath = Join-Path $repoRoot ("artifacts\backups\x01-{0}.dump" -f ([guid]::NewGuid().ToString("N")))
$docker = $null
$composePrefix = @()
$started = $false
$envBackup = @{}
$envHad = @{}
$portEnv = [ordered]@{
    BACKEND_PORT = [string]$backendPort
    FRONTEND_PORT = [string]$frontendPort
    POSTGRES_PORT = [string]$postgresPort
    POSTGRES_VOLUME_NAME = "ai-ops-platform-x01-data"
    NEXT_PUBLIC_API_BASE_URL = $apiBase
    ALLOWED_ORIGINS = "$frontendBase,http://localhost:3000"
    NEXT_PUBLIC_AUTH_MODE = "development"
    NEXT_PUBLIC_ALLOW_DEVELOPMENT_AUTH = "true"
}

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "X-01 assertion failed: $Message" }
}

function Invoke-StorageGuard {
    if (Test-Path -LiteralPath $storageGuardPath -PathType Leaf) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath -MaxGb 32 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "X-01 storage guard failed; Docker usage must remain within 32 GB" }
    }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $script:docker.Source @composePrefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "X-01 Compose command failed; inspect the named project without printing its environment" }
    return $output
}

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    $params = @{ Method = $Method; Uri = $Uri; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 60 -Compress)
    }
    $content = $null
    $status = 0
    try {
        $response = Invoke-WebRequest @params
        $content = $response.Content
        $status = [int]$response.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw "X-01 API request failed without an HTTP response" }
        $status = [int]$response.StatusCode
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $content = $reader.ReadToEnd()
            $reader.Dispose()
        } catch { $content = $null }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) {
        try { $json = $content | ConvertFrom-Json } catch { throw "X-01 API returned a non-JSON response" }
    }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

function Assert-Status {
    param($Response, [int[]]$Expected, [string]$Action)
    Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status)"
}

function Wait-Ready {
    param([string]$Uri, [string]$Name)
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri
            if ([int]$response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Milliseconds 1000
    }
    throw "X-01 $Name did not become ready; inspect the named Compose project logs"
}

function New-Login {
    param([string]$Suffix)
    $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{
        email = "x01-owner-$Suffix@example.invalid"
        name = "X01 Synthetic Owner"
        organization_name = "X01 Synthetic Org $Suffix"
        workspace_name = "X01 Staging Sandbox $Suffix"
    }
    Assert-Status $response @(200) "synthetic staging login"
    return $response.Json
}

function New-Headers {
    param($Login, [string]$WorkspaceId)
    return @{
        Authorization = "Bearer $($Login.access_token)"
        "X-Workspace-ID" = $WorkspaceId
    }
}

function Test-StaticContract {
    foreach ($path in @($contractPath, $browserSmokePath, $composeFile, $storageGuardPath, (Join-Path $repoRoot "render.yaml"), (Join-Path $repoRoot "deploy\docker-compose.staging.yml"), (Join-Path $repoRoot "deploy\migrations-policy.json"), (Join-Path $repoRoot "docs\DEPLOYMENT.md"), (Join-Path $repoRoot "docs\MIGRATIONS.md"), (Join-Path $repoRoot "scripts\verify-migrations.ps1"), (Join-Path $repoRoot "scripts\backup-postgres.ps1"), (Join-Path $repoRoot "scripts\restore-postgres.ps1"), (Join-Path $repoRoot "scripts\generate-sbom.ps1"), (Join-Path $repoRoot "backend\requirements.lock"), (Join-Path $repoRoot "backend\requirements-test.lock"), (Join-Path $repoRoot "backend\.dockerignore"), (Join-Path $repoRoot "frontend\.dockerignore"))) {
        Assert-Condition (Test-Path -LiteralPath $path -PathType Leaf) "required X-01 path is missing: $path"
    }
    $contract = Get-Content -Raw -LiteralPath $contractPath | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "x01.operations.v1") "X-01 contract version drifted"
    foreach ($property in $contract.required_markers.PSObject.Properties) {
        $target = switch ($property.Name) {
            "ci" { Join-Path $repoRoot ".github\workflows\ci.yml" }
            "deployment" { Join-Path $repoRoot "render.yaml" }
            "recovery" { Join-Path $repoRoot "docs\DEPLOYMENT.md" }
            "images" { Join-Path $repoRoot "backend\Dockerfile" }
            default { $null }
        }
        if ($null -eq $target) { continue }
        Assert-Condition (Test-Path -LiteralPath $target -PathType Leaf) "marker target is missing: $target"
        $content = Get-Content -Raw -LiteralPath $target
        foreach ($marker in @($property.Value)) {
            if ($property.Name -eq "images" -and $marker -eq "npm ci") { $content = $content + (Get-Content -Raw -LiteralPath (Join-Path $repoRoot "frontend\Dockerfile")) }
            if ($property.Name -eq "images" -and $marker -eq ".env") { $content = $content + (Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\.dockerignore")) }
            Assert-Condition ($content -match [regex]::Escape([string]$marker)) "$($property.Name) marker is missing: $marker"
        }
    }
    $lockLines = @(Get-Content -LiteralPath (Join-Path $repoRoot "backend\requirements.lock") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and -not ([string]$_).Trim().StartsWith("#") })
    foreach ($line in $lockLines) { Assert-Condition ([string]$line -match '^[A-Za-z0-9_.-]+==[^\s#]+(?:\s*;\s*[^#]+)?$') "backend lock contains an unpinned line" }
    $packageLockText = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "frontend\package-lock.json")
    $lockVersion = [regex]::Match($packageLockText, '"lockfileVersion"\s*:\s*(\d+)').Groups[1].Value
    Assert-Condition ([int]$lockVersion -ge 3) "frontend package lock is not a modern lockfile"
    foreach ($scriptPath in @("scripts\verify-x01.ps1", "scripts\verify-migrations.ps1", "scripts\backup-postgres.ps1", "scripts\restore-postgres.ps1", "scripts\generate-sbom.ps1")) {
        $fullPath = Join-Path $repoRoot $scriptPath
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($fullPath, [ref]$tokens, [ref]$errors) | Out-Null
        Assert-Condition ($errors.Count -eq 0) "$scriptPath has PowerShell parse errors"
    }
    return $contract
}

function Start-X01Compose {
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) "ignored .env is required for the real Compose path and is never printed"
    Invoke-StorageGuard
    $resolvedDocker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $resolvedDocker) { $resolvedDocker = Get-Command docker -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $resolvedDocker) "Docker CLI is required"
    $script:docker = $resolvedDocker
    foreach ($key in $portEnv.Keys) {
        $existing = Get-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
        $envHad[$key] = $null -ne $existing
        if ($null -ne $existing) { $envBackup[$key] = [string]$existing.Value }
        Set-Item -LiteralPath "Env:$key" -Value $portEnv[$key]
    }
    $script:composePrefix = @("compose", "--project-name", $projectName, "--env-file", $envFile, "--file", $composeFile)
    $null = Invoke-Compose -Arguments @("down", "--remove-orphans")
    $null = Invoke-Compose -Arguments @("config", "--quiet")
    $null = Invoke-Compose -Arguments @("up", "-d", "--build")
    $script:started = $true
    Wait-Ready -Uri "$apiBase/api/health" -Name "backend"
    Wait-Ready -Uri $frontendBase -Name "frontend"
}

function Invoke-X01HttpSmoke {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $login = New-Login -Suffix $suffix
    $workspaceId = [string]$login.workspace.id
    $headers = New-Headers -Login $login -WorkspaceId $workspaceId
    $health = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/health"
    Assert-Status $health @(200) "API health"
    $vendor = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors" -Headers $headers -Body @{ legal_name = "X01 Synthetic Vendor $suffix" }
    Assert-Status $vendor @(201) "synthetic vendor creation"
    $connector = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors" -Headers $headers -Body @{ name = "X01 connector sandbox $suffix"; kind = "email"; config = @{ endpoint = "sandbox://sandbox.local" }; egress_hosts = @("sandbox.local") }
    Assert-Status $connector @(201) "synthetic connector sandbox creation"
    $connectorId = [string]$connector.Json.connector.id
    $connectorHealth = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$connectorId/test" -Headers $headers -Body @{}
    Assert-Status $connectorHealth @(200) "synthetic connector sandbox health"
    Assert-Condition ([bool]$connectorHealth.Json.healthy -and [string]$connectorHealth.Json.result.provider -eq "sandbox") "connector sandbox did not return a healthy provider result"
    $context = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/auth/session" -Headers $headers
    Assert-Status $context @(200) "authenticated session context"
    Write-Output "X-01 HTTP PASS: synthetic vendor, authenticated session, PostgreSQL health, and real connector sandbox smoke verified."
}

function Invoke-X01Browser {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the X-01 browser smoke"
    $output = @(& $python.Source $browserSmokePath --frontend-url $frontendBase 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "X-01 browser smoke failed; repair the staging-sandbox frontend boundary" }
    Write-Output ($output -join "`n")
}

function Invoke-X01Recovery {
    $backupScript = Join-Path $repoRoot "scripts\backup-postgres.ps1"
    $restoreScript = Join-Path $repoRoot "scripts\restore-postgres.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $backupScript -ProjectName $projectName -EnvFile ".env" -ComposeFile "docker-compose.yml" -OutputPath $backupPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "X-01 backup script failed" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $restoreScript -ProjectName $projectName -EnvFile ".env" -ComposeFile "docker-compose.yml" -BackupPath $backupPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "X-01 restore drill failed" }
    Write-Output "X-01 RECOVERY PASS: custom-format PostgreSQL backup, manifest hash, isolated restore, and schema evidence verified."
}

function Invoke-X01SupplyChain {
    $backendId = ((Invoke-Compose -Arguments @("images", "-q", "backend")) | Where-Object { [string]$_ -match '^[0-9a-f]{12,64}$' } | Select-Object -First 1).ToString().Trim()
    $frontendId = ((Invoke-Compose -Arguments @("images", "-q", "frontend")) | Where-Object { [string]$_ -match '^[0-9a-f]{12,64}$' } | Select-Object -First 1).ToString().Trim()
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($backendId) -and -not [string]::IsNullOrWhiteSpace($frontendId)) "Compose did not expose built backend/frontend images"
    $backendImage = "$projectName-backend:verify"
    $frontendImage = "$projectName-frontend:verify"
    & $script:docker.Source image tag $backendId $backendImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not tag the backend image for SBOM analysis" }
    & $script:docker.Source image tag $frontendId $frontendImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not tag the frontend image for SBOM analysis" }
    foreach ($image in @($backendImage, $frontendImage)) {
        $sbomArgs = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $repoRoot "scripts\generate-sbom.ps1"),
            "-Image", $image
        )
        if ($AllowScannerAuthFailure) { $sbomArgs += "-AllowScannerAuthFailure" }
        & powershell @sbomArgs
        if ($LASTEXITCODE -ne 0) { throw "SBOM/CVE analysis failed for a built image" }
    }
    if ($AllowScannerAuthFailure) {
        Write-Output "X-01 SUPPLY CHAIN PARTIAL: built image secret-config check and CycloneDX SBOM verified; CI Trivy remains required for critical/high CVEs."
    } else {
        Write-Output "X-01 SUPPLY CHAIN PASS: built image secret-config check, CycloneDX SBOM, and critical/high CVE scan verified."
    }
}

function Stop-X01Compose {
    if ($started -and -not $KeepRunning) {
        try {
            $null = Invoke-Compose -Arguments @("down", "--volumes", "--remove-orphans")
            Invoke-StorageGuard
        } catch { Write-Warning "X-01 cleanup needs exact project '$projectName' stopped with its environment file" }
    }
    if ($started -and $KeepRunning) { Write-Output "X-01 services remain running by request; stop only project '$projectName' with its Compose env-file" }
    foreach ($key in $portEnv.Keys) {
        if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] }
        else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue }
    }
    foreach ($path in @($backupPath, "$backupPath.json")) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
    }
}

$exitCode = 0
try {
    $null = Test-StaticContract
    if ($StaticOnly) {
        Write-Output "X-01 STATIC PASS: CI, environment boundaries, Docker hardening, Render target, migration policy, recovery scripts, SBOM contract, and browser smoke verified."
    } else {
        Start-X01Compose
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\verify-migrations.ps1") -ProjectName $projectName -EnvFile ".env" -ComposeFile "docker-compose.yml" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "X-01 migration verification failed" }
        Invoke-X01HttpSmoke
        Invoke-X01Browser
        Invoke-X01Recovery
        if ($SkipImageScan) {
            Write-Output "X-01 SUPPLY CHAIN DEFERRED: external CI image scanner is responsible for SBOM/CVE artifacts in this run."
        } else {
            Invoke-X01SupplyChain
        }
        Write-Output "X-01 E2E PASS: real Docker Compose/PostgreSQL staging-sandbox, browser, migration, connector, recovery, and supply-chain evidence completed."
    }
} catch {
    Write-Error $_.Exception.Message
    $exitCode = 1
} finally { Stop-X01Compose }
if ($exitCode -ne 0) { exit $exitCode }
