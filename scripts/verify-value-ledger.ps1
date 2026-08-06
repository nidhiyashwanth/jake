[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$contractPath = Join-Path $repoRoot "tests\value\contract.json"
$browserSmokePath = Join-Path $repoRoot "tests\value\browser_smoke.py"
$fixturePath = Join-Path $repoRoot "tests\workflows\fixtures\w01.valid-workflow.json"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-mvp"
$backendPort = 8000
$frontendPort = 3000
$postgresPort = 15432
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

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "L-01 assertion failed: $Message" } }
function Copy-JsonObject { param($Object) return (($Object | ConvertTo-Json -Depth 60 -Compress) | ConvertFrom-Json) }
function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status); response body withheld." }

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try { $ErrorActionPreference = "Continue"; $output = @(& $docker.Source @composePrefix @Arguments 2>&1); $code = $LASTEXITCODE } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "L-01 Compose command failed for the managed project; inspect its service logs." }
    return $output
}

function Invoke-StorageGuard {
    if (Test-Path -LiteralPath $storageGuardPath) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "L-01 storage guard failed; Docker usage must remain within the repository budget." }
    }
}

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    $parameters = @{ Method = $Method; Uri = $Uri; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $Body) { $parameters.ContentType = "application/json"; $parameters.Body = ($Body | ConvertTo-Json -Depth 60 -Compress) }
    $content = $null; $status = 0; $responseHeaders = $null
    try { $raw = Invoke-WebRequest @parameters; $content = $raw.Content; $status = [int]$raw.StatusCode; $responseHeaders = $raw.Headers }
    catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw "L-01 API request failed without an HTTP response: $Uri" }
        $status = [int]$response.StatusCode; $responseHeaders = $response.Headers
        try { $reader = New-Object System.IO.StreamReader($response.GetResponseStream()); $content = $reader.ReadToEnd(); $reader.Dispose() } catch { $content = $null }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "L-01 API returned a non-JSON response at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json; Content = $content; Headers = $responseHeaders }
}

function Invoke-BytesBoundary {
    param([string]$Uri, [hashtable]$Headers = @{})
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    try {
        foreach ($key in $Headers.Keys) { $null = $client.DefaultRequestHeaders.TryAddWithoutValidation($key, [string]$Headers[$key]) }
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Bytes = $bytes; ContentType = [string]$response.Content.Headers.ContentType }
    } finally { $client.Dispose() }
}

function Wait-Ready { param([string]$Uri, [string]$Name) for ($attempt = 0; $attempt -lt 90; $attempt++) { try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri; if ([int]$response.StatusCode -eq 200) { return } } catch {} Start-Sleep -Milliseconds 1000 }; throw "L-01 $Name did not become ready." }
function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }
function New-Login { param([string]$Email, [string]$Name, [string]$Organization, [string]$Workspace) $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = $Email; name = $Name; organization_name = $Organization; workspace_name = $Workspace }; Assert-Status $response @(200) "development login"; return $response.Json }

function Start-L01Compose {
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) "ignored .env is required for real Compose and is never printed"
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

function Stop-L01Compose {
    if ($started -and -not $KeepRunning) { try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "L-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." } }
    if ($started -and $KeepRunning) { Write-Output "L-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) { if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue } }
}

function Test-StaticContract {
    foreach ($path in @($contractPath, $browserSmokePath, $fixturePath, $composeFile, $envFile, $storageGuardPath)) { Assert-Condition (Test-Path -LiteralPath $path -PathType Leaf) "required L-01 path is missing: $path" }
    $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "l01.value.v1") "value contract version is not canonical"
    $service = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\services\value_ledger.py") -Raw
    $routes = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\api\value_routes.py") -Raw
    $migration = Get-Content -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0016_value_ledger.py") -Raw
    $frontend = Get-Content -LiteralPath (Join-Path $repoRoot "frontend\src\components\ValueLedgerView.tsx") -Raw
    foreach ($marker in @("ValueEvent", "append_value_event", "calculate_value_rollup", "csv_value_export", "pdf_value_export", "ensure_execution_value_events")) { Assert-Condition ($service -match $marker) "value service marker is missing: $marker" }
    foreach ($marker in @("/rollup", "/events", "/drilldown", "value.export", "value.read")) { Assert-Condition ($routes -match [regex]::Escape($marker)) "value route marker is missing: $marker" }
    foreach ($marker in @("value_events", "ROW LEVEL SECURITY", "value_events_immutable", "prevent_value_event_mutation", "uq_value_events_workspace_event_key")) { Assert-Condition ($migration -match [regex]::Escape($marker)) "value migration marker is missing: $marker" }
    foreach ($marker in @("Value ledger", "No value events yet", "Export CSV", "Export PDF")) { Assert-Condition ($frontend -match [regex]::Escape($marker)) "value frontend marker is missing: $marker" }
    $browser = Get-Content -LiteralPath $browserSmokePath -Raw
    Assert-Condition ($browser -match "Value ledger" -and $browser -match "x-workspace-id") "value browser smoke markers are missing"
    $forbidden = @('p'+'sql', 'sqli'+'te', 'd'+'ocker exec', 'Invoke'+'-SqlCmd', 'database cli'+'ent')
    foreach ($word in $forbidden) { Assert-Condition (-not ($browser -match [regex]::Escape($word))) "browser smoke contains a forbidden direct-storage operation" }
    return $contract
}

function New-BaselineMetrics {
    return [ordered]@{
        volume_per_month = @{ value = 1850; unit = "instances/month"; source = "operator_interview" }
        minutes_p50 = @{ value = 6.5; unit = "minutes/instance"; source = "operator_interview" }
        minutes_p90 = @{ value = 22; unit = "minutes/instance"; source = "operator_interview" }
        fully_loaded_cost_per_hour = @{ value = 38; unit = "USD/hour"; source = "finance_rate_card" }
        error_rate_pct = @{ value = 4; unit = "percent"; source = "sampled_review" }
        cost_per_error = @{ value = 165; unit = "USD/error"; source = "finance_interview" }
        rework_rate_pct = @{ value = 11; unit = "percent"; source = "operator_interview" }
        cycle_time_hours = @{ value = 18; unit = "hours/instance"; source = "workflow_observation" }
        headcount_touching = @{ value = 4; unit = "people"; source = "org_chart" }
        peak_backlog = @{ value = 220; unit = "instances"; source = "queue_snapshot" }
        chase_volume_per_month = @{ value = 420; unit = "messages/month"; source = "mailbox_count" }
        lapse_incidents_per_month = @{ value = 7; unit = "incidents/month"; source = "incident_register" }
        audit_prep_hours_per_month = @{ value = 14; unit = "hours/month"; source = "audit_interview" }
        review_minutes = @{ value = 3; unit = "minutes/review"; source = "sampled_audit" }
    }
}

function Invoke-ValueHttpE2E {
    param($Contract)
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $organization = "L01 Verify Org $suffix"; $workspace = "L01 Verify Workspace $suffix"
    $owner = New-Login -Email "l01-owner-$suffix@example.invalid" -Name "L01 Owner" -Organization $organization -Workspace $workspace
    $workspaceId = [string]$owner.workspace.id; $headers = New-Headers $owner $workspaceId
    $process = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/processes" -Headers $headers -Body @{ name = "Compliance value process $suffix"; department = "Field Operations"; system_of_record = "Vendor compliance register"; trigger = "A certificate arrives"; inputs = @("COI document"); steps = @(@{ seq = 1; description = "Read and verify certificate"; system = "Compliance desk"; minutes_p50 = 6.5; minutes_p90 = 22; is_decision = $true }); decisions = @("Accept or review evidence"); exceptions = @("Missing endorsement"); approvals = @("Operator approval"); outputs = @("Verification record"); failure_modes = @("Unreadable scan") }
    Assert-Status $process @(201) "L-01 process creation"; $processId = [string]$process.Json.id
    $baseline = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/processes/$processId/baselines" -Headers $headers -Body @{ metrics = (New-BaselineMetrics); notes = "L-01 signed finance baseline" }
    Assert-Status $baseline @(201) "L-01 baseline creation"; $baselineId = [string]$baseline.Json.id
    $signed = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/baselines/$baselineId/sign" -Headers $headers -Body @{ signature_note = "L-01 verifier attestation" }
    Assert-Status $signed @(200) "L-01 baseline signing"; $baselineHash = [string]$signed.Json.canonical_hash
    Assert-Condition ($baselineHash -match '^[0-9a-f]{64}$') "signed baseline did not expose a canonical SHA-256 hash"

    $autoNodes = @(
        @{ key = "trigger"; type = "trigger"; label = "Certificate received"; config = @{ event = "document.received" } },
        @{ key = "notify"; type = "notify"; label = "Record auto outcome"; config = @{ input = "trigger"; template = "auto-ledger"; channel = "in_app"; recipient = "operations" } }
    )
    $autoEdges = @(@{ source = "trigger"; target = "notify" })
    $autoWorkflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body @{ key = "l01.auto.$suffix"; name = "L01 auto $suffix"; description = "Auto value evidence workflow"; process_id = $processId; baseline_id = $baselineId; nodes = $autoNodes; edges = $autoEdges; thresholds = @() }
    Assert-Status $autoWorkflow @(201) "L-01 auto workflow creation"; $autoVersionId = [string]$autoWorkflow.Json.version.id
    $autoEval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$autoVersionId/evaluation-runs" -Headers $headers -Body @{ suite_key = "w01.synthetic.baseline" }
    Assert-Status $autoEval @(201) "L-01 auto workflow evaluation"
    $autoPublish = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$autoVersionId/publish" -Headers $headers
    Assert-Status $autoPublish @(200) "L-01 auto workflow publish"

    $autoExecution = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $headers -Body @{ workflow_version_id = $autoVersionId; input = @{ document_id = "l01-auto-$suffix"; department = "Field Operations" }; idempotency_key = "l01-auto-$suffix"; max_retries = 2 }
    Assert-Status $autoExecution @(201) "L-01 auto execution creation"; $autoExecutionId = [string]$autoExecution.Json.execution.id
    $autoAdvance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$autoExecutionId/advance" -Headers $headers -Body @{ max_steps = 20; worker_id = "l01-http-worker" }
    Assert-Status $autoAdvance @(200) "L-01 auto execution advance"
    $autoDone = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$autoExecutionId" -Headers $headers
    Assert-Status $autoDone @(200) "L-01 auto execution read"; Assert-Condition ([string]$autoDone.Json.execution.status -eq "completed") "auto execution did not complete"

    $fixture = Copy-JsonObject (Get-Content -LiteralPath $fixturePath -Raw | ConvertFrom-Json)
    $promptKey = "l01.prompt.$suffix"; $modelKey = "l01.model.$suffix"
    foreach ($node in @($fixture.nodes)) { if ([string]$node.type -eq "llm") { $node.config.prompt_key = $promptKey; $node.config.model_config_key = $modelKey } }
    foreach ($prompt in @($fixture.prompts)) { $prompt.key = $promptKey }
    foreach ($model in @($fixture.model_configs)) { $model.key = $modelKey }
    $prompt = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/prompts" -Headers $headers -Body @{ key = $promptKey; body = "Return a bounded structured compliance explanation."; variables = @("document"); output_schema = @{ type = "object" } }
    Assert-Status $prompt @(201) "L-01 prompt registry setup"
    $model = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/model-configs" -Headers $headers -Body @{ key = $modelKey; provider = "synthetic"; model_id = "synthetic-model-v1"; version = 1; params = @{ temperature = 0 } }
    Assert-Status $model @(201) "L-01 model registry setup"
    foreach ($node in @($fixture.nodes)) { if ([string]$node.type -eq "tool") { $node.config | Add-Member -NotePropertyName write -NotePropertyValue $true -Force; $node.config | Add-Member -NotePropertyName writes_external -NotePropertyValue $true -Force; $node.config | Add-Member -NotePropertyName requires_approval -NotePropertyValue $true -Force; $node.config | Add-Member -NotePropertyName compensation -NotePropertyValue @{ kind = "bounded-noop"; owner = "l01-verifier" } -Force } }
    $reviewWorkflow = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflows" -Headers $headers -Body @{ key = "l01.review.$suffix"; name = "L01 reviewed $suffix"; description = "Reviewed value evidence workflow"; process_id = $processId; baseline_id = $baselineId; nodes = $fixture.nodes; edges = $fixture.edges; thresholds = $fixture.thresholds; prompts = $fixture.prompts; model_configs = $fixture.model_configs }
    Assert-Status $reviewWorkflow @(201) "L-01 reviewed workflow creation"; $reviewVersionId = [string]$reviewWorkflow.Json.version.id
    $reviewEval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$reviewVersionId/evaluation-runs" -Headers $headers -Body @{ suite_key = "w01.synthetic.baseline" }
    Assert-Status $reviewEval @(201) "L-01 reviewed workflow evaluation"
    $reviewPublish = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workflow-versions/$reviewVersionId/publish" -Headers $headers
    Assert-Status $reviewPublish @(200) "L-01 reviewed workflow publish"
    $reviewExecution = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions" -Headers $headers -Body @{ workflow_version_id = $reviewVersionId; input = @{ document_id = "l01-review-$suffix"; department = "Field Operations" }; idempotency_key = "l01-review-$suffix"; max_retries = 2 }
    Assert-Status $reviewExecution @(201) "L-01 reviewed execution creation"; $reviewExecutionId = [string]$reviewExecution.Json.execution.id
    $reviewAdvance = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$reviewExecutionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "l01-http-worker" }
    Assert-Status $reviewAdvance @(200) "L-01 reviewed execution first advance"
    $waiting = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$reviewExecutionId" -Headers $headers
    Assert-Status $waiting @(200) "L-01 reviewed waiting read"; Assert-Condition ([string]$waiting.Json.execution.status -eq "waiting_human") "reviewed execution did not stop at its human boundary"
    $resume = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$reviewExecutionId/resume" -Headers $headers -Body @{ decision = "approve"; output = @{ approved = $true }; note = "L-01 reviewer evidence" }
    Assert-Status $resume @(200) "L-01 reviewed execution resume"
    for ($round = 0; $round -lt 3; $round++) {
        $next = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$reviewExecutionId/advance" -Headers $headers -Body @{ max_steps = 50; worker_id = "l01-http-worker" }
        Assert-Status $next @(200) "L-01 reviewed execution advance"
        $state = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$reviewExecutionId" -Headers $headers
        Assert-Status $state @(200) "L-01 reviewed execution state"
        if ([string]$state.Json.execution.status -eq "waiting_human") { $more = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/runtime/executions/$reviewExecutionId/resume" -Headers $headers -Body @{ decision = "approve"; output = @{ approved = $true }; note = "L-01 final reviewer evidence" }; Assert-Status $more @(200) "L-01 final reviewer resume" }
        if ([string]$state.Json.execution.status -in @("completed", "halted", "failed", "dead_letter")) { break }
    }
    $reviewDone = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/runtime/executions/$reviewExecutionId" -Headers $headers
    Assert-Condition ([string]$reviewDone.Json.execution.status -in @("completed", "halted")) "reviewed execution did not reach a terminal state"

    $rollupResponse = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/value/rollup?implementation_cost_usd=100" -Headers $headers
    Assert-Status $rollupResponse @(200) "L-01 value rollup"; $rollup = $rollupResponse.Json
    Assert-Condition ([bool]$rollup.reconciliation.reconciles) "value rollup did not reconcile auto/reviewed/halted to ingested"
    Assert-Condition ([int]$rollup.reconciliation.ingested -eq 2) "value rollup did not count both real executions"
    Assert-Condition ([string]$rollup.baseline.id -eq $baselineId -and [string]$rollup.baseline.hash -eq $baselineHash) "value rollup lost signed baseline provenance"
    Assert-Condition ([double]$rollup.value.hours_saved -gt 0) "auto execution did not produce defensible baseline-rate time savings"
    $eventsResponse = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/value/events?limit=200" -Headers $headers
    Assert-Status $eventsResponse @(200) "L-01 value event list"; $events = @($eventsResponse.Json.items)
    Assert-Condition ($events.Count -ge 4) "value event list is missing execution evidence"
    Assert-Condition (@($events | Where-Object { $_.kind -eq "unit_processed" }).Count -eq 2) "unit_processed event count is not exactly one per execution"
    $kindSummary = (($events | ForEach-Object { [string]$_.kind }) -join ",")
    Assert-Condition (@($events | Where-Object { $_.kind -eq "time_saved" }).Count -ge 1) "time_saved event is missing; kinds=$kindSummary"
    Assert-Condition (@($events | Where-Object { $_.kind -eq "human_touch_cost" }).Count -ge 1) "human_touch_cost event is missing"
    Assert-Condition (@($events | Where-Object { [string]$_.baseline_hash -eq $baselineHash }).Count -eq $events.Count) "an event lost the signed baseline hash"
    $eventDollarTotal = (($events | Measure-Object -Property dollar_value -Sum).Sum)
    Assert-Condition ([math]::Abs([double]$eventDollarTotal - [double]$rollup.value.net_dollars_usd) -lt 0.001) "dashboard net dollars do not equal the event sum"
    $drilldown = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/value/drilldown?metric=net_dollars" -Headers $headers
    Assert-Status $drilldown @(200) "L-01 CFO drill-down"; Assert-Condition (@($drilldown.Json.items).Count -eq $events.Count) "CFO drill-down did not return the event source rows"
    Assert-Condition (@($drilldown.Json.items | Where-Object { $_.links.execution -eq "/api/runtime/executions/$autoExecutionId" }).Count -ge 1) "drill-down lost the auto execution link"

    $baselineBefore = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/baselines/$baselineId" -Headers $headers; Assert-Status $baselineBefore @(200) "L-01 baseline provenance read"; $hashBefore = [string]$baselineBefore.Json.canonical_hash
    $mutation = Invoke-JsonBoundary -Method PATCH -Uri "$apiBase/api/baselines/$baselineId" -Headers $headers -Body @{ metrics = @{ volume_per_month = @{ value = 999 } } }
    Assert-Status $mutation @(409) "L-01 signed baseline mutation fence"
    $baselineAfter = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/baselines/$baselineId" -Headers $headers; Assert-Condition ([string]$baselineAfter.Json.canonical_hash -eq $hashBefore) "signed baseline hash changed after rejected mutation"

    $csv = Invoke-BytesBoundary -Uri "$apiBase/api/value/exports/value.csv?implementation_cost_usd=100" -Headers $headers; Assert-Condition ($csv.Status -eq 200 -and [string]$csv.ContentType -like "text/csv*") "CSV export did not return text/csv"
    $csvText = [System.Text.Encoding]::UTF8.GetString($csv.Bytes); Assert-Condition ($csvText -match "reconciles" -and $csvText -match $baselineHash) "CSV export omitted reconciliation or baseline hash"
    $pdf = Invoke-BytesBoundary -Uri "$apiBase/api/value/exports/value.pdf?implementation_cost_usd=100" -Headers $headers; Assert-Condition ($pdf.Status -eq 200 -and [string]$pdf.ContentType -like "application/pdf*") "PDF export did not return application/pdf"
    Assert-Condition ($pdf.Bytes.Length -gt 1000 -and [System.Text.Encoding]::ASCII.GetString($pdf.Bytes, 0, 5) -eq "%PDF-") "PDF export did not return a valid PDF signature"
    $pdfPath = Join-Path ([IO.Path]::GetTempPath()) "ai-ops-l01-$suffix.pdf"
    try { [IO.File]::WriteAllBytes($pdfPath, $pdf.Bytes); $python = Get-Command python.exe -ErrorAction SilentlyContinue; if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }; Assert-Condition ($null -ne $python) "Python is required for PDF text validation"; & $python.Source -c "from pypdf import PdfReader; import sys; reader=PdfReader(sys.argv[1]); assert len(reader.pages) >= 1" $pdfPath; Assert-Condition ($LASTEXITCODE -eq 0) "PDF render/text validation failed" } finally { Remove-Item -LiteralPath $pdfPath -Force -ErrorAction SilentlyContinue }
    Write-Output "L-01 HTTP PASS: signed baseline provenance, auto/reviewed execution events, reconciliation, immutable baseline fence, CFO drill-down, CSV, and PDF evidence verified."
}

function Invoke-ValueBrowser {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the value browser smoke"
    $output = @(& $python.Source $browserSmokePath --frontend-url $frontendBase 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "L-01 browser smoke failed; repair the live value UI boundary and rerun." }
    Write-Output "L-01 browser PASS: authenticated value ledger, truthful empty state, and scoped API headers verified."
}

$exitCode = 0
try {
    $contract = Test-StaticContract
    if ($StaticOnly) { Write-Output "L-01 STATIC PASS: value contract, immutable migration, routes, exports, and browser smoke verified." }
    else { Start-L01Compose; Invoke-ValueHttpE2E -Contract $contract; Invoke-ValueBrowser; Write-Output "L-01 E2E PASS: real Compose/PostgreSQL HTTP and browser evidence completed." }
} catch { Write-Error $_.Exception.Message; $exitCode = 1 } finally { Stop-L01Compose }
if ($exitCode -ne 0) { exit $exitCode }
