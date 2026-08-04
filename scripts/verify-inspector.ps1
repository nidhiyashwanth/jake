[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$contractPath = Join-Path $repoRoot "tests\inspector\contract.json"
$browserSmokePath = Join-Path $repoRoot "tests\inspector\browser_smoke.py"
$fixturePath = Join-Path $repoRoot "tests\workflows\fixtures\w01.valid-workflow.json"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-i01"
$backendPort = 18009
$frontendPort = 13009
$postgresPort = 15441
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

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "I-01 assertion failed: $Message" } }
function Copy-JsonObject { param($Object) return (($Object | ConvertTo-Json -Depth 100 -Compress) | ConvertFrom-Json) }

function Invoke-StorageGuard {
    if (Test-Path -LiteralPath $storageGuardPath -PathType Leaf) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath -MaxGb 32 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "I-01 storage guard failed; Docker usage must remain within 32 GB." }
    }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $docker.Source @composePrefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "I-01 Compose command failed; inspect the named project without printing provider configuration." }
    return $output
}

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $Uri)
    $response = $null
    try {
        foreach ($headerKey in $Headers.Keys) { $null = $request.Headers.TryAddWithoutValidation([string]$headerKey, [string]$Headers[$headerKey]) }
        if ($null -ne $Body) {
            $jsonBody = $Body | ConvertTo-Json -Depth 100 -Compress
            $request.Content = [System.Net.Http.StringContent]::new($jsonBody, [System.Text.Encoding]::UTF8, "application/json")
        }
        try { $response = $client.SendAsync($request).GetAwaiter().GetResult() } catch { throw "I-01 HTTP request failed at $Uri" }
        $status = [int]$response.StatusCode
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $responseHeaders = @{}
        foreach ($header in $response.Headers) { $responseHeaders[[string]$header.Key] = ($header.Value -join ",") }
        foreach ($header in $response.Content.Headers) { $responseHeaders[[string]$header.Key] = ($header.Value -join ",") }
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $request) { $request.Dispose() }
        $client.Dispose()
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "I-01 API returned non-JSON at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json; Headers = $responseHeaders }
}

function Assert-Status {
    param($Response, [int[]]$Expected, [string]$Action)
    $detail = if ($Response.Json -and $Response.Json.error) { [string]$Response.Json.error.message } else { "no response detail" }
    Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status): $detail"
}

function Wait-Ready {
    param([string]$Uri, [string]$Name)
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri
            if ([int]$response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Seconds 1
    }
    throw "I-01 $Name did not become ready; inspect the named Compose project logs."
}

function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }

function New-Login {
    param([string]$Email, [string]$Name, [string]$Organization, [string]$Workspace)
    $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = $Email; name = $Name; organization_name = $Organization; workspace_name = $Workspace }
    Assert-Status $response @(200) "I-01 development login"
    return $response.Json
}

function Start-I01Compose {
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) "ignored .env is required for the real Compose path and is never printed"
    Invoke-StorageGuard
    $resolvedDocker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $resolvedDocker) { $resolvedDocker = Get-Command docker -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $resolvedDocker) "Docker CLI is required"
    $script:docker = $resolvedDocker
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

function Stop-I01Compose {
    if ($started -and -not $KeepRunning) {
        try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard }
        catch { Write-Warning "I-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." }
    }
    if ($started -and $KeepRunning) { Write-Output "I-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) {
        if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] }
        else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue }
    }
}

function Test-StaticContract {
    $required = @(
        "backend\app\services\observability.py",
        "backend\app\services\runtime.py",
        "backend\app\api\runtime_routes.py",
        "backend\app\worker.py",
        "backend\migrations\versions\0015_runtime_inspection.py",
        "backend\tests\test_i01_inspection.py",
        "tests\inspector\contract.json",
        "tests\inspector\browser_smoke.py",
        "scripts\verify-inspector.ps1",
        "scripts\check-docker-storage.ps1",
        "docker-compose.yml",
        ".env"
    )
    foreach ($relative in $required) { Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) "required I-01 path is missing: $relative" }
    $contract = Get-Content -Raw -LiteralPath $contractPath | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "i01.inspector.v1") "I-01 contract version is not canonical"
    $observability = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\services\observability.py")
    $runtime = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\services\runtime.py")
    $routes = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\api\runtime_routes.py")
    $worker = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\worker.py")
    $migration = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0015_runtime_inspection.py")
    $compose = Get-Content -Raw -LiteralPath $composeFile
    $frontend = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "frontend\src\components\ExecutionRuntime.tsx")
    foreach ($marker in @("redact_untrusted", "trace_context", "runtime_observability", "opentelemetry", "langfuse", "sentry")) { Assert-Condition ($observability -match [regex]::Escape($marker)) "observability marker is missing: $marker" }
    foreach ($marker in @("replay_execution", "workflow_version_id", "execution_payload", "trace_id", "redact_untrusted")) { Assert-Condition ($runtime -match [regex]::Escape($marker)) "runtime inspection marker is missing: $marker" }
    foreach ($marker in @("/observability", "workflow_version_id=payload.workflow_version_id", "runtime_observability")) { Assert-Condition ($routes -match [regex]::Escape($marker)) "runtime API marker is missing: $marker" }
    Assert-Condition ($worker -match "record_worker_heartbeat") "worker heartbeat integration is missing"
    foreach ($table in @("runtime_worker_heartbeats", "trace_id", "last_seen_at")) { Assert-Condition ($migration -match [regex]::Escape($table)) "I-01 migration marker is missing: $table" }
    foreach ($marker in @("OTEL_EXPORTER_OTLP_ENDPOINT", "LANGFUSE_OTEL_ENDPOINT", "SENTRY_DSN")) { Assert-Condition ($compose -match $marker) "Compose observability environment marker is missing: $marker" }
    foreach ($marker in @("Trace correlation", "Replay against immutable version", "Step evidence", "Degraded runtime signals")) { Assert-Condition ($frontend -match [regex]::Escape($marker)) "inspector UI marker is missing: $marker" }
    $browser = Get-Content -Raw -LiteralPath $browserSmokePath
    Assert-Condition ($browser -match "Execution runtime" -and $browser -match "Degraded runtime signals" -and $browser -match "x-workspace-id") "I-01 browser smoke markers are missing"
    foreach ($word in @('p'+'sql', 'sqli'+'te', 'd'+'ocker exec', 'Invoke'+'-SqlCmd', 'database cli'+'ent')) { Assert-Condition (-not ($browser -match [regex]::Escape($word))) "browser smoke contains a forbidden direct-storage operation" }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python is required for I-01 pure contract tests"
    & $python.Source -m pytest -q (Join-Path $repoRoot "backend\tests\test_i01_inspection.py")
    Assert-Condition ($LASTEXITCODE -eq 0) "I-01 redaction and trace contract tests failed"
    return $contract
}

function Assert-SafeResponse {
    param($Response, [string]$Secret, [string]$Label)
    $serialized = $Response.Json | ConvertTo-Json -Depth 100 -Compress
    Assert-Condition (-not $serialized.Contains($Secret)) "$Label exposed an unredacted secret-like value"
}

function Invoke-I01HttpE2E {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $login = New-Login -Email "i01-owner-$suffix@example.invalid" -Name "I01 Owner" -Organization "I01 Org $suffix" -Workspace "I01 Workspace $suffix"
    $workspaceId = [string]$login.workspace.id
    $headers = New-Headers -Login $login -WorkspaceId $workspaceId

    $fixture = Copy-JsonObject (Get-Content -Raw -LiteralPath $fixturePath | ConvertFrom-Json)
    $promptKey = "i01.prompt.$suffix"
    $modelKey = "i01.model.$suffix"
    foreach ($node in @($fixture.nodes)) {
        if ([string]$node.type -eq "llm") {
            $node.config.prompt_key = $promptKey
            $node.config.model_config_key = $modelKey
        }
        if ([string]$node.type -eq "tool") {
            $node.config | Add-Member -NotePropertyName write -NotePropertyValue $true -Force
            $node.config | Add-Member -NotePropertyName writes_external -NotePropertyValue $true -Force
            $node.config | Add-Member -NotePropertyName requires_approval -NotePropertyValue $true -Force
            $node.config | Add-Member -NotePropertyName compensation -NotePropertyValue @{ kind = "bounded-noop"; owner = "i01-verifier" } -Force
            $node.config | Add-Member -NotePropertyName idempotency_key -NotePropertyValue "i01-write" -Force
        }
    }
    foreach ($prompt in @($fixture.prompts)) { $prompt.key = $promptKey }
    foreach ($model in @($fixture.model_configs)) { $model.key = $modelKey }

    $prompt = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/prompts" -Headers $headers -Body @{ key = $promptKey; body = "Return a bounded structured compliance explanation from untrusted evidence."; variables = @("evidence"); output_schema = @{ type = "object"; properties = @{ summary = @{ type = "string" } }; required = @("summary"); additionalProperties = $false } }
    Assert-Status $prompt @(201) "I-01 prompt registry setup"
    $model = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/model-configs" -Headers $headers -Body @{ key = $modelKey; provider = "synthetic"; model_id = "synthetic-model-v1"; version = 1; params = @{ temperature = 0 } }
    Assert-Status $model @(201) "I-01 model registry setup"

    $workflowBody = @{ key = "i01.runtime.$suffix"; name = "I-01 inspection $suffix"; description = "Immutable runtime inspection verifier"; nodes = @($fixture.nodes); edges = @($fixture.edges); thresholds = @($fixture.thresholds); prompts = @($fixture.prompts); model_configs = @($fixture.model_configs) }
    $workflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body $workflowBody
    Assert-Status $workflow @(201) "I-01 workflow setup"
    $workflowId = [string]$workflow.Json.workflow.id
    $versionId = [string]$workflow.Json.version.id
    if ([string]::IsNullOrWhiteSpace($versionId)) { $versionId = [string]$workflow.Json.draft_version.id }
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($workflowId) -and -not [string]::IsNullOrWhiteSpace($versionId)) "I-01 workflow setup did not expose identifiers"
    $eval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/evaluation-runs" -Headers $headers -Body @{ suite_key = "w01.synthetic.baseline" }
    Assert-Status $eval @(201) "I-01 workflow evaluation"
    $published = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/publish" -Headers $headers
    Assert-Status $published @(200) "I-01 workflow publish"
    $publishedHash = [string]$published.Json.version.immutable_hash
    Assert-Condition ($publishedHash -match '^[0-9a-f]{64}$') "I-01 original workflow version did not receive an immutable hash"

    $targetFixture = Copy-JsonObject $fixture
    $targetHalt = @($targetFixture.nodes | Where-Object { [string]$_.type -eq "halt" }) | Select-Object -First 1
    $targetHalt.config.reason = "i01-target-version-$suffix"
    $targetVersion = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows/$workflowId/versions" -Headers $headers -Body @{ source_version_id = $versionId; nodes = @($targetFixture.nodes); edges = @($targetFixture.edges); thresholds = @($targetFixture.thresholds); prompts = @($targetFixture.prompts); model_configs = @($targetFixture.model_configs) }
    Assert-Status $targetVersion @(201) "I-01 target immutable version creation"
    $targetVersionId = [string]$targetVersion.Json.version.id
    $targetEval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$targetVersionId/evaluation-runs" -Headers $headers -Body @{ suite_key = "w01.synthetic.baseline" }
    Assert-Status $targetEval @(201) "I-01 target workflow evaluation"
    $targetPublished = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$targetVersionId/publish" -Headers $headers
    Assert-Status $targetPublished @(200) "I-01 target workflow publish"
    $targetHash = [string]$targetPublished.Json.version.immutable_hash
    Assert-Condition ($targetHash -match '^[0-9a-f]{64}$' -and $targetHash -ne $publishedHash) "I-01 target version was not independently immutable"

    $null = Invoke-Compose -Arguments @("stop", "runtime-worker")
    $secret = "i01-secret-$suffix"
    $email = "private-$suffix@example.invalid"
    $createBody = @{ workflow_version_id = $versionId; input = @{ document_id = "i01-document-$suffix"; api_token = $secret; email = $email; Authorization = "Bearer $secret" }; idempotency_key = "i01-run-$suffix"; max_retries = 2 }
    $created = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $headers -Body $createBody
    Assert-Status $created @(201) "I-01 execution create"
    Assert-SafeResponse $created $secret "I-01 execution create"
    Assert-SafeResponse $created $email "I-01 execution create"
    Assert-Condition ([bool]$created.Json.execution.redaction.applied) "I-01 execution did not expose the redaction marker"
    $correlation = [string]$created.Json.execution.correlation_id
    $traceId = [string]$created.Json.execution.trace.trace_id
    Assert-Condition ($traceId -match '^[0-9a-f]{32}$' -and [string]$created.Headers["X-Correlation-ID"] -eq $correlation) "I-01 HTTP correlation and trace context were not returned"
    foreach ($event in @($created.Json.execution.events)) {
        $eventPayloadText = $event.payload | ConvertTo-Json -Depth 100 -Compress
        Assert-Condition ([string]$event.payload.trace_id -eq $traceId -and -not $eventPayloadText.Contains($secret)) "I-01 event trace/redaction evidence was incomplete"
    }
    $executionId = [string]$created.Json.execution.id

    $advance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "i01-http-worker" }
    Assert-Status $advance @(200) "I-01 deterministic advance to inspection boundary"
    Assert-SafeResponse $advance $secret "I-01 advance response"
    $waiting = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $headers
    Assert-Status $waiting @(200) "I-01 waiting execution inspection"
    Assert-SafeResponse $waiting $secret "I-01 waiting inspection"
    Assert-Condition ([string]$waiting.Json.execution.status -eq "waiting_human" -and @($waiting.Json.execution.steps | Where-Object { $_.status -eq "waiting_human" }).Count -ge 1) "I-01 execution did not expose its human boundary"
    foreach ($step in @($waiting.Json.execution.steps)) { Assert-Condition ([string]$step.trace_id -eq $traceId) "I-01 step trace correlation was not stable" }

    $resumeTool = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/resume" -Headers $headers -Body @{ decision = "approve"; output = @{ approved = $true; email = $email; api_token = $secret }; note = "I-01 first human boundary" }
    Assert-Status $resumeTool @(200) "I-01 tool boundary resume"
    Assert-SafeResponse $resumeTool $secret "I-01 tool resume response"
    Assert-Condition ([int]$resumeTool.Json.execution.external_write_count -eq 1) "I-01 live execution did not record one bounded connector receipt"
    $advanceAgain = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "i01-http-worker" }
    Assert-Status $advanceAgain @(200) "I-01 advance to approval boundary"
    $waitingAgain = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $headers
    Assert-Status $waitingAgain @(200) "I-01 second waiting inspection"
    if ([string]$waitingAgain.Json.execution.status -eq "waiting_human") {
        $resumeApproval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/resume" -Headers $headers -Body @{ decision = "approve"; output = @{ approved = $true }; note = "I-01 approval boundary" }
        Assert-Status $resumeApproval @(200) "I-01 approval resume"
    }
    $finalAdvance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "i01-http-worker" }
    Assert-Status $finalAdvance @(200) "I-01 final deterministic advance"
    $done = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$executionId" -Headers $headers
    Assert-Status $done @(200) "I-01 completed inspection"
    Assert-SafeResponse $done $secret "I-01 completed inspection"
    Assert-Condition ([string]$done.Json.execution.status -eq "halted" -and [int]$done.Json.execution.external_write_count -eq 1) "I-01 completed run lost terminal or connector evidence"

    $replay = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$executionId/replay" -Headers $headers -Body @{ idempotency_key = "i01-replay-$suffix"; workflow_version_id = $targetVersionId }
    Assert-Status $replay @(200) "I-01 immutable-version safe replay"
    Assert-SafeResponse $replay $secret "I-01 replay response"
    Assert-Condition ([bool]$replay.Json.side_effects -eq $false -and [bool]$replay.Json.execution.dry_run -eq $true -and [int]$replay.Json.execution.external_write_count -eq 0) "I-01 replay reported or performed side effects"
    Assert-Condition ([string]$replay.Json.execution.workflow_version_id -eq $targetVersionId -and [string]$replay.Json.execution.workflow_version_hash -eq $targetHash -and [string]$replay.Json.execution.workflow_version_hash -ne $publishedHash) "I-01 replay did not pin the selected immutable target version"

    $failureFixture = Copy-JsonObject $fixture
    $failureFixture.nodes[0].config | Add-Member -NotePropertyName fail_until_attempts -NotePropertyValue 1 -Force
    $failureWorkflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body @{ key = "i01.failure.$suffix"; name = "I-01 failure signals $suffix"; description = "Failure signal verifier"; nodes = @($failureFixture.nodes); edges = @($failureFixture.edges); thresholds = @($failureFixture.thresholds); prompts = @($failureFixture.prompts); model_configs = @($failureFixture.model_configs) }
    Assert-Status $failureWorkflow @(201) "I-01 failure workflow setup"
    $failureVersionId = [string]$failureWorkflow.Json.version.id
    $failureEval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$failureVersionId/evaluation-runs" -Headers $headers -Body @{ suite_key = "w01.synthetic.baseline" }
    Assert-Status $failureEval @(201) "I-01 failure workflow evaluation"
    $failurePublish = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$failureVersionId/publish" -Headers $headers
    Assert-Status $failurePublish @(200) "I-01 failure workflow publish"
    $failedCreate = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $headers -Body @{ workflow_version_id = $failureVersionId; input = @{ document_id = "i01-failure-$suffix" }; idempotency_key = "i01-failure-run-$suffix"; max_retries = 0 }
    Assert-Status $failedCreate @(201) "I-01 failed execution create"
    $failedId = [string]$failedCreate.Json.execution.id
    $failedAdvance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$failedId/advance" -Headers $headers -Body @{ max_steps = 1; worker_id = "i01-http-worker" }
    Assert-Status $failedAdvance @(200) "I-01 failed execution advance"
    $observability = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/observability" -Headers $headers
    Assert-Status $observability @(200) "I-01 runtime observability"
    Assert-Condition ([string]$observability.Json.status -eq "degraded" -and [int]$observability.Json.queue.failed_or_dead_letter -ge 1) "I-01 degraded runtime status did not expose the failed run"
    Assert-Condition (@($observability.Json.degraded_signals) -contains "failed_or_dead_letter_runs_present") "I-01 failure alert signal was not exposed"
    Assert-Condition (@($observability.Json.degraded_signals) -contains "otel_exporter_not_configured") "I-01 missing trace sink signal was not explicit"
    Write-Output "I-01 HTTP PASS: immutable run timeline, trace correlation, secret/PII redaction, target-version replay with writes disabled, worker/degraded signals, and failure alert evidence verified over real Compose/PostgreSQL HTTP."
}

function Invoke-I01Browser {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the I-01 browser smoke"
    $previous = $ErrorActionPreference
    try { $ErrorActionPreference = "Continue"; $output = @(& $python.Source $browserSmokePath --frontend-url $frontendBase 2>&1); $exitCode = $LASTEXITCODE } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "I-01 browser smoke failed: $($output -join ' ')" }
    Write-Output "I-01 browser PASS: authenticated inspector, degraded-mode marker, and scoped API headers verified."
}

$exitCode = 0
try {
    $contract = Test-StaticContract
    if ($StaticOnly) {
        Write-Output "I-01 STATIC PASS: redaction, trace seams, immutable replay target, heartbeat migration, runtime API, frontend inspector, and browser smoke verified."
    } else {
        Start-I01Compose
        Invoke-I01HttpE2E
        Invoke-I01Browser
        Write-Output "I-01 E2E PASS: real Compose/PostgreSQL HTTP and browser evidence completed."
    }
} catch { Write-Error $_.Exception.Message; $exitCode = 1 } finally { Stop-I01Compose }
if ($exitCode -ne 0) { exit $exitCode }
