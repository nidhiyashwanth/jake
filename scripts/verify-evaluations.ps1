[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$projectName = "ai-ops-platform-e01"
$backendPort = 18008
$frontendPort = 13008
$postgresPort = 15440
$apiBase = "http://localhost:$backendPort"
$started = $false
$docker = $null
$composePrefix = @()
$envBackup = @{}
$envHad = @{}
$portEnv = [ordered]@{
    BACKEND_PORT = [string]$backendPort
    FRONTEND_PORT = [string]$frontendPort
    POSTGRES_PORT = [string]$postgresPort
    NEXT_PUBLIC_API_BASE_URL = $apiBase
    ALLOWED_ORIGINS = "http://localhost:$frontendPort,http://localhost:3000"
}

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "E-01 assertion failed: $Message" } }
function Invoke-StorageGuard { & (Join-Path $PSScriptRoot "check-docker-storage.ps1") -MaxGb 32 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { throw "E-01 storage guard failed; Docker usage must remain within 32 GB." } }

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try { $ErrorActionPreference = "Continue"; $output = @(& $docker.Source @composePrefix @Arguments 2>&1); $exitCode = $LASTEXITCODE } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "E-01 Compose command failed: $($Arguments -join ' ')`n$($output -join "`n")" }
    return $output
}

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $Uri)
    try {
        foreach ($headerKey in $Headers.Keys) { $null = $request.Headers.TryAddWithoutValidation([string]$headerKey, [string]$Headers[$headerKey]) }
        if ($null -ne $Body) {
            $jsonBody = $Body | ConvertTo-Json -Depth 100 -Compress
            $request.Content = [System.Net.Http.StringContent]::new($jsonBody, [System.Text.Encoding]::UTF8, "application/json")
        }
        try { $response = $client.SendAsync($request).GetAwaiter().GetResult() } catch { throw "E-01 HTTP request failed at $Uri" }
        $status = [int]$response.StatusCode
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    } finally {
        if ($null -ne $request) { $request.Dispose() }
        $client.Dispose()
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "E-01 API returned non-JSON at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) $detail = if ($Response.Json -and $Response.Json.error) { [string]$Response.Json.error.message } else { "no response detail" }; Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status): $detail" }
function Wait-Ready { param([string]$Uri, [string]$Name) for ($attempt = 0; $attempt -lt 90; $attempt++) { try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri; if ([int]$response.StatusCode -eq 200) { return } } catch {} Start-Sleep -Seconds 1 }; throw "E-01 $Name did not become ready; inspect the named Compose project logs." }
function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }

function Start-E01Compose {
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) "ignored .env is required and is never printed"
    Invoke-StorageGuard
    $resolvedDocker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $resolvedDocker) { $resolvedDocker = Get-Command docker -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $resolvedDocker) "Docker CLI is required"
    $script:docker = $resolvedDocker
    $script:composePrefix = @("compose", "--project-name", $projectName, "--env-file", $envFile, "--file", $composeFile)
    foreach ($key in $portEnv.Keys) {
        $existing = Get-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
        $envHad[$key] = $null -ne $existing
        if ($null -ne $existing) { $envBackup[$key] = [string]$existing.Value }
        Set-Item -LiteralPath "Env:$key" -Value $portEnv[$key]
    }
    $null = Invoke-Compose -Arguments @("down", "--remove-orphans")
    $null = Invoke-Compose -Arguments @("config", "--quiet")
    $null = Invoke-Compose -Arguments @("up", "-d", "--build")
    $script:started = $true
    Wait-Ready -Uri "$apiBase/api/health" -Name "backend"
}

function Stop-E01Compose {
    if ($started -and -not $KeepRunning) { try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "E-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." } }
    if ($started -and $KeepRunning) { Write-Output "E-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) { if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue } }
}

function Test-StaticContract {
    $required = @(
        "backend\app\services\evaluations.py",
        "backend\app\api\evaluation_routes.py",
        "backend\migrations\versions\0014_evaluation_golden_drift.py",
        "backend\tests\test_e01_evaluations.py",
        "tests\golden\e01_manifest.json",
        "tests\golden\wedge_cases.json",
        "scripts\verify-evaluations.ps1"
    )
    foreach ($relative in $required) { Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) "required E-01 path is missing: $relative" }
    $service = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\services\evaluations.py")
    $migration = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0014_evaluation_golden_drift.py")
    foreach ($marker in @("contractual_rights", "field_precision", "field_recall", "false_auto_rate", "by_sender_document_type", "canary", "metric_deltas", "publish", "detect_drift", "rolling_correction_rate")) { Assert-Condition ($service -match [regex]::Escape($marker)) "evaluation service marker is missing: $marker" }
    foreach ($table in @("golden_sets", "golden_cases", "drift_snapshots")) { Assert-Condition ($migration -match ('"' + $table + '"')) "E-01 migration is missing table '$table'" }
    $golden = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "tests\golden\wedge_cases.json") | ConvertFrom-Json
    Assert-Condition (@($golden).Count -ge 100) "the canonical wedge golden source must contain at least 100 cases"
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "tests\golden\e01_manifest.json") | ConvertFrom-Json
    Assert-Condition ([int]$manifest.minimum_exception_count_for_release -ge 20) "E-01 manifest must declare at least 20 exception cases"
    Assert-Condition ([int]$manifest.minimum_injection_canaries_for_release -ge 3) "E-01 manifest must declare at least 3 injection canaries"
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python is required for E-01 evaluation tests"
    & $python.Source -m pytest -q (Join-Path $repoRoot "backend\tests\test_e01_evaluations.py")
    Assert-Condition ($LASTEXITCODE -eq 0) "E-01 metric/gate/drift tests failed"
}

function New-GoldenCase {
    param([string]$Key, [string]$Source, [string]$Rights, [string]$Basis, [string]$Route, [string]$ExpectedRoute, [bool]$Correct, [bool]$Canary, [bool]$ExpectedCanaryPass, [bool]$PredictedCanaryPass, [bool]$CorrectionRequired = $false, [string]$DocumentType = "COI", [string]$Sender = "sender-a")
    return @{ case_key = $Key; source_type = $Source; rights_status = $Rights; rights_basis = $Basis; sender = $Sender; document_type = $DocumentType; input = @{ fixture = $Key }; expected = @{ fields = @{ named_insured = "Acme LLC"; expiry = "2099-12-31" }; route = $ExpectedRoute; correct = $Correct; correction_required = $CorrectionRequired; canary_pass = $ExpectedCanaryPass }; prediction = @{ fields = @{ named_insured = "Acme LLC"; expiry = "2099-12-31" }; route = $Route; canary_pass = $PredictedCanaryPass }; canary = $Canary }
}

function Invoke-E01HttpE2E {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $loginResponse = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = "e01-owner-$suffix@example.invalid"; name = "E01 Owner"; organization_name = "E01 Org $suffix"; workspace_name = "E01 Workspace $suffix" }
    Assert-Status $loginResponse @(200) "E-01 development login"
    $login = $loginResponse.Json
    $workspaceId = [string]$login.workspace.id
    $headers = New-Headers -Login $login -WorkspaceId $workspaceId

    $fixture = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "tests\workflows\fixtures\w01.valid-workflow.json") | ConvertFrom-Json
    $workflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body @{ key = "e01-$suffix"; name = "E-01 evaluation workflow $suffix"; description = "Golden evaluation fixture"; nodes = @($fixture.nodes); edges = @($fixture.edges); thresholds = @($fixture.thresholds); prompts = @($fixture.prompts); model_configs = @($fixture.model_configs) }
    Assert-Status $workflow @(201) "workflow fixture creation"
    $versionId = [string]$workflow.Json.version.id
    if ([string]::IsNullOrWhiteSpace($versionId)) { $versionId = [string]$workflow.Json.draft_version.id }
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($versionId)) "workflow fixture did not expose a version id"

    # Workflow publish validation resolves external prompt/model registry entries.
    # The fixture embeds the references in the version definition, so create the
    # corresponding workspace-scoped records before exercising the E-01 gate.
    $promptSetup = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/prompts" -Headers $headers -Body @{
        key = "compliance.explain"
        description = "Synthetic structured evidence explanation prompt"
        body = "Summarize the observed compliance evidence and choose the risk level from the output schema."
        variables = @("evidence")
        output_schema = @{
            type = "object"
            properties = @{ summary = @{ type = "string" }; risk_level = @{ type = "string" } }
            required = @("summary", "risk_level")
            additionalProperties = $false
        }
    }
    Assert-Status $promptSetup @(201) "prompt registry setup"
    $modelSetup = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/model-configs" -Headers $headers -Body @{
        key = "compliance.default"
        provider = "synthetic"
        model_id = "synthetic-model-v1"
        version = 1
        params = @{ temperature = 0 }
    }
    Assert-Status $modelSetup @(201) "model registry setup"

    $passingCases = @(
        (New-GoldenCase -Key "corrected-coi" -Source "corrected" -Rights "contractual_rights" -Basis "Customer-approved corrected case under the workspace SOW." -Route "auto" -ExpectedRoute "auto" -Correct $true -Canary $false -ExpectedCanaryPass $true -PredictedCanaryPass $true),
        (New-GoldenCase -Key "manual-review-w9" -Source "manual" -Rights "manual_review" -Basis "Operator-curated review case with evaluation-use approval." -Route "review" -ExpectedRoute "review" -Correct $true -Canary $false -ExpectedCanaryPass $true -PredictedCanaryPass $true -DocumentType "W9" -Sender "sender-b"),
        (New-GoldenCase -Key "injection-canary-1" -Source "canary" -Rights "synthetic" -Basis "Synthetic prompt-injection canary for release testing." -Route "halt" -ExpectedRoute "halt" -Correct $true -Canary $true -ExpectedCanaryPass $true -PredictedCanaryPass $true)
    )
    $passingSet = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/evaluations/golden-sets" -Headers $headers -Body @{ workflow_version_id = $versionId; name = "E-01 release set $suffix"; status = "active"; source_policy = @{ contractual_rights_required = $true; curated_from = "corrected-and-manual-cases" }; gate = @{ max_false_auto_rate = 0.02; min_exact_match_rate = 0.90; min_macro_field_precision = 0.90; min_macro_field_recall = 0.90; max_correction_rate = 0.15; max_regression_delta = 0.03 }; cases = $passingCases }
    Assert-Status $passingSet @(201) "passing golden set creation"
    $passingSetId = [string]$passingSet.Json.golden_set.id
    $canonicalHash = [string]$passingSet.Json.golden_set.canonical_hash
    Assert-Condition ($canonicalHash -match '^[0-9a-f]{64}$') "golden set did not expose a canonical reproducible hash"
    Assert-Condition ([int]$passingSet.Json.golden_set.case_count -eq 3) "passing golden set case count was not persisted"

    $rightsDenied = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/evaluations/golden-sets" -Headers $headers -Body @{ workflow_version_id = $versionId; name = "invalid-rights-$suffix"; status = "active"; cases = @(@{ case_key = "unknown-rights"; source_type = "manual"; rights_status = "unknown"; rights_basis = "not approved"; expected = @{}; prediction = @{} }) }
    Assert-Status $rightsDenied @(422) "golden case rights boundary"

    $baselineRun = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/evaluations/golden" -Headers $headers -Body @{ golden_set_id = $passingSetId }
    Assert-Status $baselineRun @(201) "passing golden evaluation"
    Assert-Condition ([bool]$baselineRun.Json.passed) "passing golden evaluation was blocked"
    $baselineId = [string]$baselineRun.Json.evaluation.id
    Assert-Condition ([string]$baselineRun.Json.evaluation.evaluation_type -eq "golden.e01") "evaluation type was not persisted"
    Assert-Condition ([math]::Abs([double]$baselineRun.Json.evaluation.metrics.exact_match_rate - 1.0) -lt 0.0001) "baseline exact-match metric was not reproducible"

    $regressionCases = @(
        (New-GoldenCase -Key "regression-good" -Source "corrected" -Rights "contractual_rights" -Basis "Customer-approved corrected case under the workspace SOW." -Route "auto" -ExpectedRoute "auto" -Correct $true -Canary $false -ExpectedCanaryPass $true -PredictedCanaryPass $true),
        (New-GoldenCase -Key "regression-false-auto" -Source "corrected" -Rights "contractual_rights" -Basis "Customer-approved corrected case under the workspace SOW." -Route "auto" -ExpectedRoute "review" -Correct $false -Canary $false -ExpectedCanaryPass $true -PredictedCanaryPass $true),
        (New-GoldenCase -Key "regression-canary" -Source "canary" -Rights "synthetic" -Basis "Synthetic prompt-injection canary for release testing." -Route "auto" -ExpectedRoute "halt" -Correct $false -Canary $true -ExpectedCanaryPass $true -PredictedCanaryPass $false)
    )
    $regressionSet = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/evaluations/golden-sets" -Headers $headers -Body @{ workflow_version_id = $versionId; name = "E-01 regression set $suffix"; status = "active"; source_policy = @{ contractual_rights_required = $true; curated_from = "regression-and-canary-cases" }; cases = $regressionCases }
    Assert-Status $regressionSet @(201) "regression golden set creation"
    $regressionRun = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/evaluations/golden" -Headers $headers -Body @{ golden_set_id = $regressionSet.Json.golden_set.id; baseline_evaluation_id = $baselineId }
    Assert-Status $regressionRun @(201) "regression golden evaluation"
    Assert-Condition (-not [bool]$regressionRun.Json.passed) "regression golden evaluation unexpectedly passed"
    Assert-Condition (@($regressionRun.Json.failing_cases).Count -ge 1) "regression evaluation did not expose failing case ids"
    Assert-Condition (-not [string]::IsNullOrWhiteSpace([string]$regressionRun.Json.evaluation.metric_deltas.false_auto_rate)) "regression metric delta was not exposed"

    $publishBlocked = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/publish" -Headers $headers
    Assert-Status $publishBlocked @(409) "publish regression block"
    Assert-Condition ([string]$publishBlocked.Json.error.code -eq "EVALUATION_FAILED") "publish regression block did not expose EVALUATION_FAILED"

    $recoveredRun = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/evaluations/golden" -Headers $headers -Body @{ golden_set_id = $passingSetId; baseline_evaluation_id = $baselineId }
    Assert-Status $recoveredRun @(201) "recovered passing golden evaluation"
    Assert-Condition ([bool]$recoveredRun.Json.passed) "recovered passing golden evaluation did not pass"
    $published = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$versionId/publish" -Headers $headers
    Assert-Status $published @(200) "publish after passing golden evaluation"

    $drift = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/evaluations/drift" -Headers $headers -Body @{ workflow_version_id = $versionId; window_key = "2026-08-04-week-1"; baseline_correction_rate = 0.10; max_delta = 0.20; min_samples = 5; observations = @(
        @{ sender = "sender-a"; document_type = "COI"; corrected = $true }, @{ sender = "sender-a"; document_type = "COI"; corrected = $true }, @{ sender = "sender-a"; document_type = "COI"; corrected = $true }, @{ sender = "sender-a"; document_type = "COI"; corrected = $true }, @{ sender = "sender-a"; document_type = "COI"; corrected = $true },
        @{ sender = "sender-b"; document_type = "W9"; corrected = $false }, @{ sender = "sender-b"; document_type = "W9"; corrected = $false }, @{ sender = "sender-b"; document_type = "W9"; corrected = $false }, @{ sender = "sender-b"; document_type = "W9"; corrected = $false }, @{ sender = "sender-b"; document_type = "W9"; corrected = $false }
    ) }
    Assert-Status $drift @(201) "rolling drift snapshot"
    Assert-Condition ([bool]$drift.Json.alerted) "rolling correction-rate drift did not alert"
    Assert-Condition (@($drift.Json.snapshot.alerts).Count -eq 1) "drift emitted an unexpected number of group alerts"
    Assert-Condition ([string]$drift.Json.snapshot.alerts[0].group -eq "sender-a|COI") "drift alert did not identify the changed sender/document layout"

    $driftList = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/evaluations/drift" -Headers $headers
    Assert-Status $driftList @(200) "drift history"
    $auditLog = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/audit?limit=500" -Headers $headers
    Assert-Status $auditLog @(200) "evaluation audit log"
    $actions = @($auditLog.Json.items | ForEach-Object { [string]$_.action })
    foreach ($required in @("evaluation.golden_set.created", "evaluation.golden_completed", "evaluation.drift.alert", "workflow.publish_denied")) { Assert-Condition ($actions -contains $required) "evaluation audit log is missing $required" }

    Write-Output "E-01 HTTP PASS: rights-labelled golden sets, field precision/recall and operational metrics, canary/regression evaluation, immutable metric snapshots, publish blocking/recovery, rolling sender/document drift alerting, and audit evidence verified over real Compose/PostgreSQL HTTP."
}

$exitCode = 0
try {
    Test-StaticContract
    if ($StaticOnly) {
        Write-Output "E-01 STATIC PASS: rights manifest, canonical 100-case source, metrics, canary, regression, publish-gate, drift service, migration, and tests verified."
    } else {
        Start-E01Compose
        Invoke-E01HttpE2E
    }
} catch { Write-Error $_.Exception.Message; $exitCode = 1 } finally { Stop-E01Compose }
if ($exitCode -ne 0) { exit $exitCode }
