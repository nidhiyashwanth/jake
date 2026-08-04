[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$projectName = "ai-ops-platform-q01"
$backendPort = 18007
$frontendPort = 13007
$postgresPort = 15439
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

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "Q-01 assertion failed: $Message" } }
function Invoke-StorageGuard { & (Join-Path $PSScriptRoot "check-docker-storage.ps1") -MaxGb 32 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { throw "Q-01 storage guard failed; Docker usage must remain within 32 GB." } }

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try { $ErrorActionPreference = "Continue"; $output = @(& $docker.Source @composePrefix @Arguments 2>&1); $exitCode = $LASTEXITCODE } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "Q-01 Compose command failed: $($Arguments -join ' ')`n$($output -join "`n")" }
    return $output
}

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    $params = @{ Method = $Method; Uri = $Uri; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $Body) { $params.ContentType = "application/json"; $params.Body = ($Body | ConvertTo-Json -Depth 80 -Compress) }
    $content = $null; $status = 0
    try { $raw = Invoke-WebRequest @params; $content = $raw.Content; $status = [int]$raw.StatusCode }
    catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw "Q-01 HTTP request failed without a response at $Uri" }
        $status = [int]$response.StatusCode
        try { $reader = [System.IO.StreamReader]::new($response.GetResponseStream()); $content = $reader.ReadToEnd(); $reader.Dispose() } catch { $content = $null }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "Q-01 API returned non-JSON at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) $detail = if ($Response.Json -and $Response.Json.error) { [string]$Response.Json.error.message } else { "no response detail" }; Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status): $detail" }
function Wait-Ready { param([string]$Uri, [string]$Name) for ($attempt = 0; $attempt -lt 90; $attempt++) { try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri; if ([int]$response.StatusCode -eq 200) { return } } catch {} Start-Sleep -Seconds 1 }; throw "Q-01 $Name did not become ready; inspect the named Compose project logs." }
function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }

function Start-Q01Compose {
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

function Stop-Q01Compose {
    if ($started -and -not $KeepRunning) { try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "Q-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." } }
    if ($started -and $KeepRunning) { Write-Output "Q-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) { if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue } }
}

function Test-StaticContract {
    $required = @(
        "backend\app\services\confidence.py",
        "backend\app\api\confidence_routes.py",
        "backend\migrations\versions\0013_confidence_routing.py",
        "backend\tests\test_q01_confidence.py",
        "scripts\verify-confidence.ps1"
    )
    foreach ($relative in $required) { Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) "required Q-01 path is missing: $relative" }
    $service = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\services\confidence.py")
    $routes = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\api\confidence_routes.py")
    $migration = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0013_confidence_routing.py")
    foreach ($marker in @("FORMULA_VERSION", "WEIGHTS", "extraction_consistency", "validation_quality", "value_at_risk_score", "model_confidence_used", "_stable_sample", "simulate", "false_auto_alert", "threshold.rollback")) { Assert-Condition ($service -match [regex]::Escape($marker)) "confidence service marker is missing: $marker" }
    foreach ($route in @("/confidence/threshold-sets", "/confidence/assess", "/confidence/simulate", "/confidence/audits")) { Assert-Condition ($routes -match [regex]::Escape($route)) "confidence route is missing: $route" }
    foreach ($table in @("confidence_threshold_sets", "confidence_assessments", "confidence_audits")) { Assert-Condition ($migration -match ('"' + $table + '"')) "Q-01 migration is missing table '$table'" }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python is required for Q-01 calibration tests"
    & $python.Source -m pytest -q (Join-Path $repoRoot "backend\tests\test_q01_confidence.py")
    Assert-Condition ($LASTEXITCODE -eq 0) "Q-01 calibration/property tests failed"
}

function Invoke-Q01HttpE2E {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $loginResponse = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = "q01-owner-$suffix@example.invalid"; name = "Q01 Owner"; organization_name = "Q01 Org $suffix"; workspace_name = "Q01 Workspace $suffix" }
    Assert-Status $loginResponse @(200) "Q-01 development login"
    $login = $loginResponse.Json
    $workspaceId = [string]$login.workspace.id
    $headers = New-Headers -Login $login -WorkspaceId $workspaceId

    $fixture = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "tests\workflows\fixtures\w01.valid-workflow.json") | ConvertFrom-Json
    $workflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body @{ key = "q01-$suffix"; name = "Q-01 confidence workflow $suffix"; description = "Threshold simulator fixture"; nodes = @($fixture.nodes); edges = @($fixture.edges); thresholds = @($fixture.thresholds); prompts = @($fixture.prompts); model_configs = @($fixture.model_configs) }
    Assert-Status $workflow @(201) "workflow fixture creation"
    $workflowVersionId = [string]$workflow.Json.version.id
    if ([string]::IsNullOrWhiteSpace($workflowVersionId)) { $workflowVersionId = [string]$workflow.Json.draft_version.id }
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($workflowVersionId)) "workflow fixture did not expose a version id"

    $v1 = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/threshold-sets" -Headers $headers -Body @{ workflow_version_id = $workflowVersionId; version = 1; status = "active"; auto_threshold = 0.95; review_threshold = 0.75; halt_threshold = 0.5; value_at_risk_limit = 10000; sample_rate = 1.0 }
    Assert-Status $v1 @(201) "conservative threshold v1"
    $v1Id = [string]$v1.Json.threshold_set.id
    $v2 = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/threshold-sets" -Headers $headers -Body @{ workflow_version_id = $workflowVersionId; version = 2; status = "active"; auto_threshold = 0.85; review_threshold = 0.65; halt_threshold = 0.45; value_at_risk_limit = 10000; sample_rate = 1.0 }
    Assert-Status $v2 @(201) "active threshold v2"
    $v2Id = [string]$v2.Json.threshold_set.id
    Assert-Condition ([string]$v2.Json.threshold_set.previous_threshold_set_id -eq $v1Id) "threshold v2 did not preserve its previous version"

    $strongSignals = @{ extraction_consistency = 0.9; validation_severity = 0.05; matching_score = 0.9; novelty_score = 0.05; sender_history_score = 0.9; value_at_risk = 500; model_confidence = 0.01; evidence = @{ source = "q01-golden" } }
    $auto = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/assess" -Headers $headers -Body (@{ assessment_key = "q01-auto-$suffix"; workflow_version_id = $workflowVersionId } + $strongSignals)
    Assert-Status $auto @(201) "high-confidence assessment"
    Assert-Condition ([string]$auto.Json.assessment.route -eq "auto") "strong observable signals did not route auto"
    Assert-Condition ([bool]$auto.Json.assessment.evidence.model_confidence_used -eq $false) "self-reported model confidence was used"
    Assert-Condition ($null -ne $auto.Json.audit) "100% sampled audit was not created for the high-confidence auto-run"
    $auditId = [string]$auto.Json.audit.id

    $review = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/assess" -Headers $headers -Body (@{ assessment_key = "q01-review-$suffix"; workflow_version_id = $workflowVersionId; extraction_consistency = 0.75; validation_severity = 0.25; matching_score = 0.75; novelty_score = 0.25; sender_history_score = 0.75; value_at_risk = 500; model_confidence = 0.99 } )
    Assert-Status $review @(201) "review assessment"
    Assert-Condition ([string]$review.Json.assessment.route -eq "review") "medium-confidence assessment did not route review"
    $halt = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/assess" -Headers $headers -Body (@{ assessment_key = "q01-halt-$suffix"; workflow_version_id = $workflowVersionId; extraction_consistency = 0.1; validation_severity = 0.95; matching_score = 0.1; novelty_score = 0.95; sender_history_score = 0.1; value_at_risk = 500; model_confidence = 0.99 } )
    Assert-Status $halt @(201) "halt assessment"
    Assert-Condition ([string]$halt.Json.assessment.route -eq "halt") "low-confidence assessment did not route halt"

    $replay = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/assess" -Headers $headers -Body (@{ assessment_key = "q01-auto-$suffix"; workflow_version_id = $workflowVersionId } + $strongSignals)
    Assert-Status $replay @(201) "idempotent assessment replay"
    Assert-Condition ([bool]$replay.Json.idempotent_replay) "assessment retry created a second decision"

    $simulation = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/simulate" -Headers $headers -Body @{ cases = @(
        @{ case_key = "golden-1"; extraction_consistency = 0.9; validation_severity = 0.05; matching_score = 0.9; novelty_score = 0.05; sender_history_score = 0.9; value_at_risk = 500; known_correct = $false },
        @{ case_key = "golden-2"; extraction_consistency = 0.75; validation_severity = 0.25; matching_score = 0.75; novelty_score = 0.25; sender_history_score = 0.75; value_at_risk = 500; known_correct = $true },
        @{ case_key = "golden-3"; extraction_consistency = 0.1; validation_severity = 0.95; matching_score = 0.1; novelty_score = 0.95; sender_history_score = 0.1; value_at_risk = 500; required_halt = $true; known_correct = $true }
    ); thresholds = @(
        @{ label = "conservative"; auto_threshold = 0.95; review_threshold = 0.75; halt_threshold = 0.5; value_at_risk_limit = 10000 },
        @{ label = "default"; auto_threshold = 0.85; review_threshold = 0.65; halt_threshold = 0.45; value_at_risk_limit = 10000 }
    ) }
    Assert-Status $simulation @(200) "threshold simulator"
    foreach ($result in @($simulation.Json.results)) { Assert-Condition ([bool]$result.reconciles) "simulator counts did not reconcile at $($result.label)"; Assert-Condition (([int]$result.auto_count + [int]$result.review_count + [int]$result.halt_count) -eq 3) "simulator lost a case at $($result.label)" }
    Assert-Condition ([int]$simulation.Json.results[1].false_auto_count -eq 1) "simulator did not calculate the known false-auto" 

    $outcome = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/audits/$auditId/outcome" -Headers $headers -Body @{ actual_correct = $false; outcome_summary = "Operator correction exposed a false auto." }
    Assert-Status $outcome @(200) "false-auto sampled audit outcome"
    Assert-Condition ([string]$outcome.Json.audit.status -eq "alerted" -and [bool]$outcome.Json.audit.false_auto) "false-auto alert was not persisted"
    Assert-Condition ([string]$outcome.Json.audit.rollback_threshold_set_id -eq $v1Id) "false-auto did not roll back to the previous threshold"
    $postRollback = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/confidence/assess" -Headers $headers -Body (@{ assessment_key = "q01-post-rollback-$suffix"; workflow_version_id = $workflowVersionId } + $strongSignals)
    Assert-Status $postRollback @(201) "post-rollback assessment"
    Assert-Condition ([string]$postRollback.Json.assessment.route -eq "review") "rollback did not block the former auto route"

    $audits = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/confidence/audits" -Headers $headers
    Assert-Status $audits @(200) "sampled audit list"
    Assert-Condition (@($audits.Json.items).Count -ge 1) "sampled audit list was empty"
    $auditLog = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/audit?limit=500" -Headers $headers
    Assert-Status $auditLog @(200) "confidence threshold audit log"
    $actions = @($auditLog.Json.items | ForEach-Object { [string]$_.action })
    foreach ($required in @("confidence.threshold.created", "confidence.false_auto_alert", "confidence.threshold.rollback")) { Assert-Condition ($actions -contains $required) "audit log is missing $required" }

    Write-Output "Q-01 HTTP PASS: six-signal deterministic calibration, per-workflow threshold versions, simulator reconciliation, two-percent sampling floor, model-confidence rejection, false-auto alert, and threshold rollback verified over real Compose/PostgreSQL HTTP."
}

$exitCode = 0
try {
    Test-StaticContract
    if ($StaticOnly) {
        Write-Output "Q-01 STATIC PASS: deterministic formula, threshold invariants, simulator, sample floor, audit rollback, routes, migration, and calibration tests verified."
    } else {
        Start-Q01Compose
        Invoke-Q01HttpE2E
    }
} catch { Write-Error $_.Exception.Message; $exitCode = 1 } finally { Stop-Q01Compose }
if ($exitCode -ne 0) { exit $exitCode }
