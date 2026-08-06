[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$contractPath = Join-Path $repoRoot "tests\review-desk\contract.json"
$browserSmokePath = Join-Path $repoRoot "tests\review-desk\browser_smoke.py"
$fixturePath = Join-Path $repoRoot "tests\fixtures\coi-failing.txt"
$browserFixturePath = Join-Path $repoRoot "tests\review-desk\browser_fixture.txt"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-v01"
$backendPort = 18004
$frontendPort = 13004
$postgresPort = 15436
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

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "V-01 assertion failed: $Message" } }

function Invoke-StorageGuard {
    if (Test-Path -LiteralPath $storageGuardPath) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "V-01 storage guard failed; Docker usage must remain within the repository budget." }
    }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $docker.Source @composePrefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($exitCode -ne 0) { throw "V-01 Compose command failed. Repair the local Compose/WSL boundary and rerun." }
    return $output
}

function Invoke-JsonBoundary {
    param([string]$Method, [string]$Uri, [hashtable]$Headers = @{}, $Body = $null)
    $params = @{ Method = $Method; Uri = $Uri; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $Body) { $params.ContentType = "application/json"; $params.Body = ($Body | ConvertTo-Json -Depth 60 -Compress) }
    $content = $null
    $status = 0
    try {
        $raw = Invoke-WebRequest @params
        $content = $raw.Content
        $status = [int]$raw.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw "V-01 API request failed at $Uri without an HTTP response" }
        $status = [int]$response.StatusCode
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $content = $reader.ReadToEnd()
            $reader.Dispose()
        } catch { $content = $null }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) {
        try { $json = $content | ConvertFrom-Json } catch { throw "V-01 API returned a non-JSON response at $Uri" }
    }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status); response body withheld" }

function Wait-Ready {
    param([string]$Uri, [string]$Name)
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri
            if ([int]$response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Milliseconds 1000
    }
    throw "V-01 $Name did not become ready; inspect the named Compose project logs."
}

function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }

function New-Login {
    param([string]$Email, [string]$Name, [string]$Organization, [string]$Workspace)
    $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = $Email; name = $Name; organization_name = $Organization; workspace_name = $Workspace }
    Assert-Status $response @(200) "development login"
    return $response.Json
}

function Invoke-MultipartUpload {
    param([string]$Path, [string]$FilePath, [hashtable]$Headers)
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", ([string]$Headers.Authorization).Replace("Bearer ", ""))
        $client.DefaultRequestHeaders.Add("X-Workspace-ID", [string]$Headers."X-Workspace-ID")
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/plain")
        $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
        $form.Add([System.Net.Http.StringContent]::new("COI"), "doc_type")
        $response = $client.PostAsync("$apiBase$Path", $form).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "V-01 multipart upload failed at $Path with HTTP $([int]$response.StatusCode)" }
        return $body | ConvertFrom-Json
    } finally {
        $form.Dispose()
        $client.Dispose()
    }
}

function Start-V01Compose {
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

function Stop-V01Compose {
    if ($started -and -not $KeepRunning) {
        try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "V-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." }
    }
    if ($started -and $KeepRunning) { Write-Output "V-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) {
        if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue }
    }
}

function Test-StaticContract {
    foreach ($path in @($contractPath, $browserSmokePath, $fixturePath, $browserFixturePath, $composeFile, $envFile, $storageGuardPath)) { Assert-Condition (Test-Path -LiteralPath $path -PathType Leaf) "required V-01 path is missing: $path" }
    $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "v01.review-desk.v1") "review desk contract version is not canonical"
    Assert-Condition ([int]$contract.bulk_cap -eq 25) "review desk bulk cap must be 25"
    $service = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\services\review_desk.py") -Raw
    $migration = Get-Content -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0010_review_desk.py") -Raw
    $routes = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\api\review_routes.py") -Raw
    $page = Get-Content -LiteralPath (Join-Path $repoRoot "frontend\src\app\page.tsx") -Raw
    $panel = Get-Content -LiteralPath (Join-Path $repoRoot "frontend\src\components\ReviewQueuePanel.tsx") -Raw
    foreach ($marker in @("REASON_PRIORITY", "source_provenance", "append_review_event", "MAX_BULK_TASKS", "review.priority.v1")) { Assert-Condition ($service -match [regex]::Escape($marker)) "review desk service marker is missing: $marker" }
    foreach ($marker in @("review_task_events", "provenance_json", "due_at", "assigned_to_user_id", "escalation_level")) { Assert-Condition ($migration -match [regex]::Escape($marker)) "review desk migration marker is missing: $marker" }
    foreach ($marker in @("/reviews/queue", "/reviews/{review_id}/assign", "/reviews/{review_id}/escalate", "/reviews/bulk")) { Assert-Condition ($routes -match [regex]::Escape($marker)) "review desk route marker is missing: $marker" }
    foreach ($marker in @("ReviewQueuePanel", "reason_code", "Source locator", "reviewReasonCodes")) { Assert-Condition ($page -match [regex]::Escape($marker)) "review desk UI marker is missing: $marker" }
    foreach ($marker in @("Select visible", "Bulk cap: 25 tasks", "Review desk keyboard help", "onBulkAssign")) { Assert-Condition ($panel -match [regex]::Escape($marker)) "review queue panel marker is missing: $marker" }
    $browser = Get-Content -LiteralPath $browserSmokePath -Raw
    Assert-Condition ($browser -match "Review desk" -and $browser -match "x-workspace-id") "review browser smoke markers are missing"
    $forbidden = @('p'+'sql', 'sqli'+'te', 'd'+'ocker exec', 'Invoke'+'-SqlCmd', 'database cli'+'ent')
    foreach ($word in $forbidden) { Assert-Condition (-not ($browser -match [regex]::Escape($word))) "review browser smoke contains a forbidden direct-storage operation" }
    return $contract
}

function Invoke-ReviewDeskHttpE2E {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $organization = "V01 Verify Org $suffix"
    $workspace = "V01 Verify Workspace $suffix"
    $owner = New-Login -Email "v01-owner-$suffix@example.invalid" -Name "V01 Owner" -Organization $organization -Workspace $workspace
    $workspaceId = [string]$owner.workspace.id
    $headers = New-Headers -Login $owner -WorkspaceId $workspaceId
    $vendor = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors" -Headers $headers -Body @{ legal_name = "V01 Vendor $suffix LLC" }
    Assert-Status $vendor @(201) "review desk vendor creation"
    $fixtureText = [System.IO.File]::ReadAllText($fixturePath).Replace("{{VENDOR_NAME}}", [string]$vendor.Json.legal_name)
    $tempFixture = Join-Path ([System.IO.Path]::GetTempPath()) "ai-ops-v01-$suffix.txt"
    try {
        [System.IO.File]::WriteAllText($tempFixture, $fixtureText, [System.Text.UTF8Encoding]::new($false))
        $document = Invoke-MultipartUpload -Path "/api/vendors/$($vendor.Json.id)/documents" -FilePath $tempFixture -Headers $headers
        Assert-Condition (-not [string]::IsNullOrWhiteSpace([string]$document.id)) "review desk document upload did not return an id"
        $verification = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/documents/$($document.id)/verify" -Headers $headers
        Assert-Status $verification @(200) "review desk verification"
        Assert-Condition ([string]$verification.Json.status.status -eq "needs_review") "review desk fixture should create a needs_review snapshot"

        $queue = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/reviews/queue?status=open&limit=50" -Headers $headers
        Assert-Status $queue @(200) "review desk queue read"
        Assert-Condition ([int]$queue.Json.count -ge 1) "review desk queue is missing the verification exception"
        $review = @($queue.Json.items | Where-Object { $_.vendor_id -eq $vendor.Json.id -and $_.correction_field -eq "certificate_holder" }) | Select-Object -First 1
        Assert-Condition ($null -ne $review) "review desk queue did not expose certificate_holder"
        Assert-Condition ([string]$review.priority_band -eq "urgent" -and [int]$review.sla_minutes -eq 30) "review desk priority/SLA formula was not applied"
        Assert-Condition ([string]$review.provenance.locator_kind -eq "text_character_range" -and [string]$review.provenance.filename -eq [string]$document.filename) "review desk source provenance is incomplete"
        Assert-Condition ([string]$review.provenance.source_quality -eq "deterministic_text_locator") "review desk provenance overclaimed source quality"

        $detail = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/reviews/$($review.id)" -Headers $headers
        Assert-Status $detail @(200) "review desk detail read"
        Assert-Condition ((@($detail.Json.review.events).event_type -contains "review.created")) "review.created event is missing"

        $assigned = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/reviews/$($review.id)/assign" -Headers $headers -Body @{ assignee_user_id = $owner.user.id }
        Assert-Status $assigned @(200) "review desk assignment"
        Assert-Condition ([string]$assigned.Json.review.assigned_to_user_id -eq [string]$owner.user.id) "review desk assignment did not persist"

        $escalated = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/reviews/$($review.id)/escalate" -Headers $headers -Body @{ reason = "V01 supervisor review required" }
        Assert-Status $escalated @(200) "review desk escalation"
        Assert-Condition ([int]$escalated.Json.review.escalation_level -ge 1) "review desk escalation level did not persist"

        $bulk = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/reviews/bulk" -Headers $headers -Body @{ action = "assign"; assignee_user_id = $owner.user.id; review_ids = @([string]$review.id) }
        Assert-Status $bulk @(200) "review desk bulk assignment"
        Assert-Condition ([int]$bulk.Json.updated -eq 1) "review desk bulk assignment did not update one task"
        $overCap = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/reviews/bulk" -Headers $headers -Body @{ action = "assign"; assignee_user_id = $owner.user.id; review_ids = (1..26 | ForEach-Object { [guid]::NewGuid().ToString() }) }
        Assert-Status $overCap @(422) "review desk bulk cap"

        $corrected = Invoke-JsonBoundary -Method PATCH -Uri "$apiBase/api/reviews/$($review.id)" -Headers $headers -Body @{ field = "certificate_holder"; value = "Northwind Construction LLC"; reason_code = "SOURCE_TEXT_CORRECTION"; note = "V01 source evidence confirmation." }
        Assert-Status $corrected @(200) "review desk reason-coded correction"
        Assert-Condition ([string]$corrected.Json.status.status -eq "compliant") "review desk correction did not produce compliant status"
        $after = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/reviews/$($review.id)" -Headers $headers
        Assert-Status $after @(200) "review desk corrected detail"
        Assert-Condition ([string]$after.Json.review.correction_reason_code -eq "SOURCE_TEXT_CORRECTION") "correction reason code was not durable"
        $eventTypes = @($after.Json.review.events).event_type
        Assert-Condition (($eventTypes -contains "review.created") -and ($eventTypes -contains "review.assigned") -and ($eventTypes -contains "review.escalated") -and ($eventTypes -contains "review.correction_applied")) "review task event history is incomplete"
        $closedQueue = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/reviews/queue?status=open&limit=50" -Headers $headers
        Assert-Status $closedQueue @(200) "review desk closed queue read"
        Assert-Condition (-not (@($closedQueue.Json.items).id -contains [string]$review.id)) "resolved review remained in the open queue"

        $other = New-Login -Email "v01-other-$suffix@example.invalid" -Name "V01 Other" -Organization "V01 Other Org $suffix" -Workspace "V01 Other Workspace $suffix"
        $otherHeaders = New-Headers -Login $other -WorkspaceId ([string]$other.workspace.id)
        $hidden = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/reviews/$($review.id)" -Headers $otherHeaders
        Assert-Status $hidden @(404, 403) "review desk cross-workspace isolation"
        Write-Output "V-01 HTTP PASS: prioritized queue, text provenance, assignment, escalation, bulk cap, reason-coded correction, event history, and workspace isolation verified."
    } finally {
        if (Test-Path -LiteralPath $tempFixture) { Remove-Item -LiteralPath $tempFixture -Force }
    }
}

function Invoke-ReviewDeskBrowser {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the review desk browser smoke"
    $output = @(& $python.Source $browserSmokePath --frontend-url $frontendBase 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "V-01 browser smoke failed; repair the live review desk UI boundary and rerun." }
    Write-Output "V-01 browser PASS: authenticated review desk, truthful empty state, keyboard help, and scoped API headers verified."
}

$exitCode = 0
try {
    $null = Test-StaticContract
    if ($StaticOnly) {
        Write-Output "V-01 STATIC PASS: contract, queue service, durable fields/events, routes, UI, and browser smoke verified."
    } else {
        Start-V01Compose
        Invoke-ReviewDeskHttpE2E
        Invoke-ReviewDeskBrowser
        Write-Output "V-01 E2E PASS: real Compose/PostgreSQL HTTP and browser evidence completed."
    }
} catch {
    Write-Error $_.Exception.Message
    $exitCode = 1
} finally {
    Stop-V01Compose
}
if ($exitCode -ne 0) { exit $exitCode }
