[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$contractPath = Join-Path $repoRoot "tests\runtime\contract.json"
$browserSmokePath = Join-Path $repoRoot "tests\runtime\browser_smoke.py"
$fixturePath = Join-Path $repoRoot "tests\workflows\fixtures\w01.valid-workflow.json"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-r01"
$backendPort = 18003
$frontendPort = 13003
$postgresPort = 15435
$apiBase = "http://localhost:$backendPort"
$frontendBase = "http://localhost:$frontendPort"
$docker = $null
$composePrefix = @()
$started = $false
$envBackup = @{}
$envHad = @{}
$portEnv = [ordered]@{
    BACKEND_PORT = [string]$backendPort
    FRONTEND_PORT = [string]$frontendPort
    POSTGRES_PORT = [string]$postgresPort
    NEXT_PUBLIC_API_BASE_URL = $apiBase
    ALLOWED_ORIGINS = "$frontendBase,http://localhost:3000"
}

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "R-01 assertion failed: $Message" } }

function Copy-JsonObject { param($Object) return (($Object | ConvertTo-Json -Depth 60 -Compress) | ConvertFrom-Json) }

function Invoke-Compose {
    param([string[]]$Arguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Compose writes normal lifecycle progress to stderr. Capture it without
        # letting PowerShell's Stop policy mistake that progress for a failure.
        $ErrorActionPreference = "Continue"
        $output = @(& $docker.Source @composePrefix @Arguments 2>&1)
        $composeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($composeExitCode -ne 0) { throw "R-01 Compose command failed. Repair the local Compose/WSL boundary and rerun." }
    return $output
}

function Invoke-StorageGuard { if (Test-Path -LiteralPath $storageGuardPath) { & powershell -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { throw "R-01 storage guard failed; Docker usage must remain within the repository budget." } } }

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    $params = @{ Method = $Method; Uri = $Uri; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $Body) { $params.ContentType = "application/json"; $params.Body = ($Body | ConvertTo-Json -Depth 60 -Compress) }
    $content = $null
    $status = 0
    $responseHeaders = $null
    try {
        $raw = Invoke-WebRequest @params
        $content = $raw.Content
        $status = [int]$raw.StatusCode
        $responseHeaders = $raw.Headers
    } catch {
        # Windows PowerShell 5.1 has no -SkipHttpErrorCheck. Preserve the
        # response status/body for contract assertions without printing it.
        $response = $_.Exception.Response
        if ($null -eq $response) { throw "R-01 API request failed at $Uri without an HTTP response" }
        $status = [int]$response.StatusCode
        $responseHeaders = $response.Headers
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $content = $reader.ReadToEnd()
            $reader.Dispose()
        } catch {
            $content = $null
        }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "R-01 API returned a non-JSON response at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json; Headers = $responseHeaders }
}

function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) Assert-Condition -Condition ($Expected -contains [int]$Response.Status) -Message "$Action returned HTTP $($Response.Status); response body withheld." }

function Wait-Ready { param([string]$Uri, [string]$Name) for ($attempt = 0; $attempt -lt 90; $attempt++) { try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri; if ([int]$response.StatusCode -eq 200) { return } } catch {} Start-Sleep -Milliseconds 1000 }; throw "R-01 $Name did not become ready; inspect the named Compose project logs." }

function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }

function New-Login { param([string]$Email, [string]$Name, [string]$Organization, [string]$Workspace) $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = $Email; name = $Name; organization_name = $Organization; workspace_name = $Workspace }; Assert-Status $response @(200) "development login"; return $response.Json }

function Start-R01Compose {
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) "ignored .env is required for the real Compose path and is never printed"
    Invoke-StorageGuard
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $docker) { $docker = Get-Command docker -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $docker) "Docker CLI is required"
    $script:docker = $docker
    $script:composePrefix = @("compose", "--project-name", $projectName, "--env-file", $envFile, "--file", $composeFile)
    $null = Invoke-Compose -Arguments @("down", "--remove-orphans")
    foreach ($key in $portEnv.Keys) {
        $existing = Get-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
        $envHad[$key] = $null -ne $existing
        if ($null -ne $existing) { $envBackup[$key] = [string]$existing.Value }
        Set-Item -LiteralPath "Env:$key" -Value $portEnv[$key]
    }
    $null = Invoke-Compose -Arguments @("config", "--quiet")
    $null = Invoke-Compose -Arguments @("up", "-d", "--build")
    $script:started = $true
    Wait-Ready -Uri "$apiBase/api/health" -Name "backend"
    Wait-Ready -Uri $frontendBase -Name "frontend"
}

function Stop-R01Compose {
    if ($started -and -not $KeepRunning) { try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "R-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." } }
    if ($started -and $KeepRunning) { Write-Output "R-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) { if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue } }
}

function Test-StaticContract {
    foreach ($path in @($contractPath, $browserSmokePath, $fixturePath, $composeFile, $envFile, $storageGuardPath)) { Assert-Condition (Test-Path -LiteralPath $path -PathType Leaf) "required R-01 path is missing: $path" }
    $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "r01.runtime.v1") "runtime contract version is not canonical"
    $service = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\services\runtime.py") -Raw
    $migration = Get-Content -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0009_runtime.py") -Raw
    $compose = Get-Content -LiteralPath $composeFile -Raw
    foreach ($marker in @("Execution", "ExternalWriteReceipt", "OutboxEvent", "replay_execution", "recover_stale_claims")) { Assert-Condition ($service -match $marker) "runtime service marker is missing: $marker" }
    $usesRowLocking = ($service -match "with_for_update\s*\(\s*skip_locked\s*=\s*True") -or (($service -match "FOR UPDATE") -and ($service -match "SKIP LOCKED"))
    Assert-Condition $usesRowLocking "runtime claim must use row locking with skip-locked semantics"
    foreach ($table in @("executions", "execution_steps", "outbox_events", "external_write_receipts", "execution_events")) { Assert-Condition ($migration -match ('"' + $table + '"')) "runtime migration is missing table '$table'" }
    Assert-Condition ($compose -match "runtime-worker" -and $compose -match "app.worker") "Compose worker wiring is missing"
    $browser = Get-Content -LiteralPath $browserSmokePath -Raw
    Assert-Condition ($browser -match "Execution runtime" -and $browser -match "x-workspace-id") "runtime browser smoke markers are missing"
    $forbidden = @('p'+'sql', 'sqli'+'te', 'd'+'ocker exec', 'Invoke'+'-SqlCmd', 'database cli'+'ent')
    foreach ($word in $forbidden) { Assert-Condition (-not ($browser -match [regex]::Escape($word))) "browser smoke contains a forbidden direct-storage operation" }
    return $contract
}

function Invoke-RuntimeHttpE2E {
    param($Contract)
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $organization = "R01 Verify Org $suffix"
    $workspace = "R01 Verify Workspace $suffix"
    $owner = New-Login -Email "r01-owner-$suffix@example.invalid" -Name "R01 Owner" -Organization $organization -Workspace $workspace
    $workspaceId = [string]$owner.workspace.id
    $headers = New-Headers -Login $owner -WorkspaceId $workspaceId
    $fixture = Copy-JsonObject (Get-Content -LiteralPath $fixturePath -Raw | ConvertFrom-Json)
    $promptKey = "r01.prompt.$suffix"
    $modelKey = "r01.model.$suffix"
    foreach ($node in @($fixture.nodes)) { if ([string]$node.type -eq "llm") { $node.config.prompt_key = $promptKey; $node.config.model_config_key = $modelKey } }
    foreach ($prompt in @($fixture.prompts)) { $prompt.key = $promptKey }
    foreach ($model in @($fixture.model_configs)) { $model.key = $modelKey }
    foreach ($node in @($fixture.nodes)) {
        if ([string]$node.type -eq "tool") {
            $node.config | Add-Member -NotePropertyName write -NotePropertyValue $true -Force
            $node.config | Add-Member -NotePropertyName writes_external -NotePropertyValue $true -Force
            $node.config | Add-Member -NotePropertyName requires_approval -NotePropertyValue $true -Force
            $node.config | Add-Member -NotePropertyName compensation -NotePropertyValue @{ kind = "bounded-noop"; owner = "runtime-verifier" } -Force
        }
    }
    $prompt = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/prompts" -Headers $headers -Body @{ key = $promptKey; body = "Return a bounded structured compliance explanation."; variables = @("document"); output_schema = @{ type = "object" } }
    Assert-Status $prompt @(201) "runtime prompt registry setup"
    $model = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/model-configs" -Headers $headers -Body @{ key = $modelKey; provider = "synthetic"; model_id = "synthetic-model-v1"; version = 1; params = @{ temperature = 0 } }
    Assert-Status $model @(201) "runtime model registry setup"
    $workflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body @{ key = "r01.runtime.$suffix"; name = "R01 runtime $suffix"; description = "Durable runtime verifier workflow"; nodes = @($fixture.nodes); edges = @($fixture.edges); thresholds = @($fixture.thresholds); prompts = @($fixture.prompts); model_configs = @($fixture.model_configs) }
    Assert-Status $workflow @(201) "runtime workflow setup"
    $versionId = [string]$workflow.Json.version.id
    $eval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/evaluation-runs" -Headers $headers -Body @{ suite_key = "w01.synthetic.baseline" }
    Assert-Status $eval @(201) "runtime workflow evaluation"
    $published = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/publish" -Headers $headers
    Assert-Status $published @(200) "runtime workflow publish"
    $publishedHash = [string]$published.Json.version.immutable_hash
    Assert-Condition ($publishedHash -match '^[0-9a-f]{64}$') "runtime run did not receive a pinned SHA-256 version hash"

    $null = Invoke-Compose -Arguments @("stop", "runtime-worker")
    $createBody = @{ workflow_version_id = $versionId; input = @{ document_id = "runtime-$suffix" }; idempotency_key = "r01-run-$suffix"; max_retries = 2 }
    $created = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $headers -Body $createBody
    Assert-Status $created @(201) "runtime execution create"
    $executionId = [string]$created.Json.execution.id
    $repeat = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $headers -Body $createBody
    Assert-Status $repeat @(200, 201) "runtime idempotent execution create"
    Assert-Condition ([string]$repeat.Json.execution.id -eq $executionId -and [bool]$repeat.Json.idempotent) "same idempotency key created a duplicate execution"
    $advance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "r01-http-worker" }
    Assert-Status $advance @(200) "runtime first deterministic advance"
    $current = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $headers
    Assert-Status $current @(200) "runtime waiting inspection"
    Assert-Condition ([string]$current.Json.execution.status -eq "waiting_human") "runtime did not stop at the human approval boundary"
    $resume = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/resume" -Headers $headers -Body @{ decision = "approve"; output = @{ approved = $true }; note = "R01 acceptance" }
    Assert-Status $resume @(200) "runtime human resume"
    Assert-Condition ([int]$resume.Json.execution.external_write_count -eq 1) "approved external tool write did not create exactly one idempotency receipt"
    $secondWait = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "r01-http-worker" }
    Assert-Status $secondWait @(200) "runtime second deterministic advance"
    $waitingAgain = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $headers
    if ([string]$waitingAgain.Json.execution.status -eq "waiting_human") {
        $resumeAgain = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/resume" -Headers $headers -Body @{ decision = "approve"; output = @{ approved = $true }; note = "R01 final approval" }
        Assert-Status $resumeAgain @(200) "runtime final human resume"
    }
    $finalAdvance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "r01-http-worker" }
    Assert-Status $finalAdvance @(200) "runtime final advance"
    $done = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $headers
    Assert-Status $done @(200) "runtime completed inspection"
    Assert-Condition ([string]$done.Json.execution.status -eq "halted") "runtime halt terminal was not durable"
    $beforeWrites = [int]$done.Json.execution.external_write_count
    $repeatAdvance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "r01-http-worker" }
    Assert-Status $repeatAdvance @(200) "runtime duplicate delivery probe"
    Assert-Condition ([int]$repeatAdvance.Json.execution.external_write_count -eq $beforeWrites) "duplicate delivery changed the external-write receipt count"
    $replay = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/replay" -Headers $headers -Body @{ idempotency_key = "r01-replay-$suffix" }
    Assert-Status $replay @(200) "runtime safe replay"
    Assert-Condition ([bool]$replay.Json.side_effects -eq $false -and [int]$replay.Json.execution.external_write_count -eq 0) "replay reported or performed side effects"
    $dispatch = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/outbox/dispatch" -Headers $headers -Body @{ worker_id = "r01-outbox"; limit = 100 }
    Assert-Status $dispatch @(200) "runtime outbox dispatch"
    $recovered = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/workers/recover" -Headers $headers -Body $null
    Assert-Status $recovered @(200) "runtime stale claim recovery"

    $viewerEmail = "r01-viewer-$suffix@example.invalid"
    $invite = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workspaces/$workspaceId/members" -Headers $headers -Body @{ email = $viewerEmail; name = "R01 Viewer"; role = "viewer" }
    Assert-Status $invite @(201, 200) "runtime viewer invitation"
    $viewer = New-Login -Email $viewerEmail -Name "R01 Viewer" -Organization $organization -Workspace $workspace
    $viewerHeaders = New-Headers -Login $viewer -WorkspaceId $workspaceId
    $denied = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $viewerHeaders -Body @{ workflow_version_id = $versionId; input = @{}; idempotency_key = "r01-viewer-$suffix" }
    Assert-Status $denied @(403) "runtime RBAC create denial"

    $other = New-Login -Email "r01-other-$suffix@example.invalid" -Name "R01 Other" -Organization "R01 Other Org $suffix" -Workspace "Other Workspace $suffix"
    $otherHeaders = New-Headers -Login $other -WorkspaceId $other.workspace.id
    $hidden = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $otherHeaders
    Assert-Status $hidden @(404, 403) "runtime cross-workspace isolation"
    Write-Output "R-01 HTTP PASS: pinned version, idempotency, deterministic steps, human wait/resume, external-write fence, replay, outbox, recovery, RBAC, and workspace isolation verified."
}

function Invoke-RuntimeBrowser {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the runtime browser smoke"
    $output = @(& $python.Source $browserSmokePath --frontend-url $frontendBase 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "R-01 browser smoke failed; repair the first live runtime UI boundary and rerun." }
    Write-Output "R-01 browser PASS: authenticated runtime surface, truthful empty state, and scoped API headers verified."
}

$exitCode = 0
try {
    $contract = Test-StaticContract
    if ($StaticOnly) {
        Write-Output "R-01 STATIC PASS: runtime contract, durable tables, lock markers, Compose worker, and browser smoke verified."
    } else {
        Start-R01Compose
        Invoke-RuntimeHttpE2E -Contract $contract
        Invoke-RuntimeBrowser
        Write-Output "R-01 E2E PASS: real Compose/PostgreSQL HTTP and browser evidence completed."
    }
} catch { Write-Error $_.Exception.Message; $exitCode = 1 } finally { Stop-R01Compose }
if ($exitCode -ne 0) { exit $exitCode }
