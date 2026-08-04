[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$projectName = "ai-ops-platform-p01"
$backendPort = 18006
$frontendPort = 13006
$postgresPort = 15438
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

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "P-01 assertion failed: $Message" } }
function Invoke-StorageGuard { & (Join-Path $PSScriptRoot "check-docker-storage.ps1") -MaxGb 32 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { throw "P-01 storage guard failed; Docker usage must remain within 32 GB." } }

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try { $ErrorActionPreference = "Continue"; $output = @(& $docker.Source @composePrefix @Arguments 2>&1); $exitCode = $LASTEXITCODE } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "P-01 Compose command failed: $($Arguments -join ' ')`n$($output -join "`n")" }
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
        if ($null -eq $response) { throw "P-01 HTTP request failed without a response at $Uri" }
        $status = [int]$response.StatusCode
        try { $reader = [System.IO.StreamReader]::new($response.GetResponseStream()); $content = $reader.ReadToEnd(); $reader.Dispose() } catch { $content = $null }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "P-01 API returned non-JSON at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) $detail = if ($Response.Json -and $Response.Json.error) { [string]$Response.Json.error.message } else { "no response detail" }; Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status): $detail" }
function Wait-Ready { param([string]$Uri, [string]$Name) for ($attempt = 0; $attempt -lt 90; $attempt++) { try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri; if ([int]$response.StatusCode -eq 200) { return } } catch {} Start-Sleep -Seconds 1 }; throw "P-01 $Name did not become ready; inspect the named Compose project logs." }
function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }
function New-Login { param([string]$Email, [string]$Name, [string]$Organization, [string]$Workspace) $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = $Email; name = $Name; organization_name = $Organization; workspace_name = $Workspace }; Assert-Status $response @(200) "development login"; return $response.Json }

function Invoke-MultipartUpload {
    param([string]$Path, [string]$FilePath, [hashtable]$Headers, [string]$DocType)
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, "$apiBase$Path")
    try {
        $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", [string]($Headers.Authorization -replace '^Bearer\s+', ''))
        $request.Headers.Add("X-Workspace-ID", [string]$Headers["X-Workspace-ID"])
        $form = [System.Net.Http.MultipartFormDataContent]::new()
        try {
            $bytes = [System.IO.File]::ReadAllBytes($FilePath)
            $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
            $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/plain")
            $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
            $form.Add([System.Net.Http.StringContent]::new($DocType), "doc_type")
            $request.Content = $form
            $response = $client.SendAsync($request).GetAwaiter().GetResult()
            $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $json = if ($body) { $body | ConvertFrom-Json } else { $null }
            return [pscustomobject]@{ Status = [int]$response.StatusCode; Json = $json }
        } finally { $form.Dispose() }
    } finally { $request.Dispose(); $client.Dispose() }
}

function Start-P01Compose {
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

function Stop-P01Compose {
    if ($started -and -not $KeepRunning) { try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "P-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." } }
    if ($started -and $KeepRunning) { Write-Output "P-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) { if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue } }
}

function Test-StaticContract {
    $required = @(
        "backend\app\services\compliance_catalog.py",
        "backend\app\services\compliance_rules.py",
        "backend\app\services\compliance.py",
        "backend\app\services\chase.py",
        "backend\app\api\compliance_routes.py",
        "backend\migrations\versions\0012_compliance_catalog_chase.py",
        "tests\golden\wedge_cases.json",
        "scripts\verify-compliance.ps1"
    )
    foreach ($relative in $required) { Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) "required P-01 path is missing: $relative" }
    $catalog = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\services\compliance_catalog.py")
    $migration = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0012_compliance_catalog_chase.py")
    $chase = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "backend\app\services\chase.py")
    foreach ($marker in @("RULE_LIBRARY", "REASON_CODES", "DOCUMENT_TYPES", "named_insured_match", "expiry_buffer", "w9_legal_name_match", "lien_waiver_type", "osha_training_current")) { Assert-Condition ($catalog -match [regex]::Escape($marker)) "catalog marker is missing: $marker" }
    foreach ($table in @("vendor_entities", "compliance_requirement_sets", "compliance_requirements", "vendor_requirements", "coverage_lines", "reason_code_taxonomy", "chase_threads", "chase_events")) { Assert-Condition ($migration -match ('"' + $table + '"')) "P-01 migration is missing table '$table'" }
    foreach ($marker in @("CHASE_APPROVAL_REQUIRED", "CHASE_UNSAFE_NEGOTIATION", "CHASE_WEEKLY_CAP_EXCEEDED", "chase.compliant_and_verified", "cc_internal_owner")) { Assert-Condition ($chase -match [regex]::Escape($marker)) "chase guardrail marker is missing: $marker" }
    $golden = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "tests\golden\wedge_cases.json") | ConvertFrom-Json
    Assert-Condition (@($golden).Count -ge 100) "golden set must contain at least 100 cases"
    $fixtures = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "tests\fixtures\p01") -Filter *.txt -File)
    Assert-Condition ($fixtures.Count -ge 12) "v1 document-type fixture set is incomplete"
    $forbidden = @('d'+'ocker exec', 'Invoke'+'-SqlCmd', 'database cli'+'ent', 'p'+'sql', 'sqli'+'te')
    $scriptText = Get-Content -Raw -LiteralPath $PSCommandPath
    foreach ($word in $forbidden) { Assert-Condition (-not ($scriptText -match [regex]::Escape($word))) "P-01 verifier contains a forbidden direct-storage operation: $word" }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python is required for the deterministic P-01 rule suite"
    & $python.Source -m pytest -q (Join-Path $repoRoot "backend\tests\test_p01_compliance_rules.py")
    Assert-Condition ($LASTEXITCODE -eq 0) "the 100-case/35-rule deterministic suite failed"
}

function Invoke-P01HttpE2E {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $owner = New-Login -Email "p01-owner-$suffix@example.invalid" -Name "P01 Owner" -Organization "P01 Org $suffix" -Workspace "P01 Workspace $suffix"
    $workspaceId = [string]$owner.workspace.id
    $headers = New-Headers -Login $owner -WorkspaceId $workspaceId

    $types = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/compliance/document-types" -Headers $headers
    Assert-Status $types @(200) "document taxonomy"
    Assert-Condition (@($types.Json.items).Count -ge 12) "v1 document taxonomy is incomplete"
    $rules = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/compliance/rule-library" -Headers $headers
    Assert-Status $rules @(200) "rule library"
    Assert-Condition ([int]$rules.Json.count -eq 35) "rule library did not expose exactly 35 deterministic rules"

    $requirementSetResponse = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/compliance/requirement-sets" -Headers $headers -Body @{ name = "Wedge Compliance v1"; version = 1; status = "active" }
    Assert-Status $requirementSetResponse @(201) "requirement-set creation"
    $requirementSet = $requirementSetResponse.Json.requirement_set
    $requirements = @($requirementSet.requirements)
    Assert-Condition ($requirements.Count -eq 35) "active requirement set did not seed all 35 rules"
    $reasonCodes = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/compliance/reason-codes" -Headers $headers
    Assert-Status $reasonCodes @(200) "reason-code taxonomy"
    Assert-Condition ([int]$reasonCodes.Json.count -ge 20) "reason-code taxonomy was not seeded"

    $vendorResponse = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors" -Headers $headers -Body @{ legal_name = "Acme Mechanical P01 $suffix LLC"; dba_names = @("Acme Field Services $suffix"); risk_tier = "high" }
    Assert-Status $vendorResponse @(201) "vendor creation"
    $vendor = $vendorResponse.Json
    $entity = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors/$($vendor.id)/entities" -Headers $headers -Body @{ name = "Acme Field Services $suffix"; relationship = "dba" }
    Assert-Status $entity @(201) "vendor DBA entity"
    $binding = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors/$($vendor.id)/requirement-bindings" -Headers $headers -Body @{ requirement_set_id = $requirementSet.id; overrides = @{ gl_occurrence_minimum = 2000000 } }
    Assert-Status $binding @(201) "vendor requirement binding"

    $coiFixture = Join-Path $repoRoot "tests\fixtures\p01\coi-complete.txt"
    $coiContent = [System.IO.File]::ReadAllText($coiFixture).Replace("Acme Mechanical LLC", $vendor.legal_name)
    $coiTemp = Join-Path ([System.IO.Path]::GetTempPath()) "p01-coi-$suffix.txt"
    [System.IO.File]::WriteAllText($coiTemp, $coiContent, [System.Text.UTF8Encoding]::new($false))
    try { $coiUpload = Invoke-MultipartUpload -Path "/api/vendors/$($vendor.id)/documents" -FilePath $coiTemp -Headers $headers -DocType "COI" } finally { Remove-Item -LiteralPath $coiTemp -Force -ErrorAction SilentlyContinue }
    Assert-Status $coiUpload @(201) "COI upload"
    $coiDocument = $coiUpload.Json
    $coiVerification = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/documents/$($coiDocument.id)/verify" -Headers $headers
    Assert-Status $coiVerification @(200) "35-rule COI verification"
    $coiFailures = (@($coiVerification.Json.status.failing_requirements) -join ",")
    Assert-Condition ([string]$coiVerification.Json.status.status -eq "compliant") "complete COI did not pass the active versioned rule set; failing rules: $coiFailures"
    Assert-Condition (@($coiVerification.Json.checks).Count -eq 21) "COI verification did not evaluate the 21 applicable deterministic rules"

    $secondUpload = Invoke-MultipartUpload -Path "/api/vendors/$($vendor.id)/documents" -FilePath $coiFixture -Headers $headers -DocType "COI"
    Assert-Status $secondUpload @(201) "COI superseding upload"
    $detail = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/vendors/$($vendor.id)" -Headers $headers
    Assert-Status $detail @(200) "vendor document history"
    $old = @($detail.Json.documents) | Where-Object { $_.id -eq $coiDocument.id } | Select-Object -First 1
    Assert-Condition ($null -ne $old -and [string]$old.status -eq "superseded" -and -not [string]::IsNullOrWhiteSpace([string]$old.superseded_by)) "document supersession did not preserve the old source as historical evidence"

    $acordFixture = Join-Path $repoRoot "tests\fixtures\p01\acord-855-complete.txt"
    $acordUpload = Invoke-MultipartUpload -Path "/api/vendors/$($vendor.id)/documents" -FilePath $acordFixture -Headers $headers -DocType "ACORD_855"
    Assert-Status $acordUpload @(201) "ACORD 855 upload"
    $acordVerify = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/documents/$($acordUpload.Json.id)/verify" -Headers $headers
    Assert-Status $acordVerify @(200) "ACORD 855 verification"
    Assert-Condition ([string]$acordVerify.Json.status.status -eq "compliant") "ACORD 855 fixture did not pass endorsement rules"

    $w9Fixture = Join-Path $repoRoot "tests\fixtures\p01\w9-complete.txt"
    $w9Temp = Join-Path ([System.IO.Path]::GetTempPath()) "p01-w9-$suffix.txt"
    [System.IO.File]::WriteAllText($w9Temp, ([System.IO.File]::ReadAllText($w9Fixture).Replace("Acme Mechanical LLC", $vendor.legal_name)), [System.Text.UTF8Encoding]::new($false))
    try { $w9Upload = Invoke-MultipartUpload -Path "/api/vendors/$($vendor.id)/documents" -FilePath $w9Temp -Headers $headers -DocType "W9" } finally { Remove-Item -LiteralPath $w9Temp -Force -ErrorAction SilentlyContinue }
    Assert-Status $w9Upload @(201) "W-9 upload"
    $w9Verify = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/documents/$($w9Upload.Json.id)/verify" -Headers $headers
    Assert-Status $w9Verify @(200) "W-9 verification"
    Assert-Condition ([string]$w9Verify.Json.status.status -eq "compliant") "W-9 fixture did not pass the name/currentness rules"

    $connector = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors" -Headers $headers -Body @{ name = "P01 customer sender $suffix"; kind = "email"; config = @{ endpoint = "sandbox://sandbox.local" }; egress_hosts = @("sandbox.local") }
    Assert-Status $connector @(201) "customer-owned sender creation"
    $connectorId = [string]$connector.Json.connector.id
    $health = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$connectorId/test" -Headers $headers -Body @{}
    Assert-Status $health @(200) "customer-owned sender health"
    Assert-Condition ([bool]$health.Json.healthy) "customer-owned sender sandbox did not become healthy"
    $aiRequirement = $requirements | Where-Object { $_.key -eq "additional_insured_present" } | Select-Object -First 1
    $chase = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors/$($vendor.id)/chases" -Headers $headers -Body @{ requirement_id = $aiRequirement.id; customer_sender_connector_id = $connectorId; expected_doc_type = "ACORD_855"; max_attempts = 3; max_messages_per_week = 3; touch_schedule_days = @(0, 1, 2) }
    Assert-Status $chase @(201) "chase thread creation"
    $chaseId = [string]$chase.Json.chase.id
    $approvalDenied = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/chases/$chaseId/touch" -Headers $headers -Body @{ body = "Please send the missing endorsement."; approved = $false }
    Assert-Status $approvalDenied @(409) "chase approval boundary"
    $unsafe = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/chases/$chaseId/touch" -Headers $headers -Body @{ body = "Please approve this vendor and negotiate a lower limit."; approved = $true }
    Assert-Status $unsafe @(422) "unsafe negotiation guardrail"
    $sent = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/chases/$chaseId/touch" -Headers $headers -Body @{ body = "Please send the ACORD 855 endorsement for the open requirement."; approved = $true }
    Assert-Status $sent @(200) "sandbox chase touch"
    $unmatched = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/chases/$chaseId/reply" -Headers $headers -Body @{ body = "Here is a tax form."; attachment_document_id = $w9Upload.Json.id }
    Assert-Status $unmatched @(200) "unmatched chase attachment"
    Assert-Condition ([string]$unmatched.Json.chase.status -eq "awaiting_reply") "unmatched attachment incorrectly closed the chase"
    $matched = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/chases/$chaseId/reply" -Headers $headers -Body @{ body = "Here is the requested endorsement."; attachment_document_id = $acordUpload.Json.id }
    Assert-Status $matched @(200) "matched verified chase reply"
    Assert-Condition ([string]$matched.Json.chase.status -eq "compliant_and_verified") "chase did not emit the compliant-and-verified success event"
    $successEvent = @(@($matched.Json.chase.events) | Where-Object { $_.event_type -eq "chase.compliant_and_verified" })
    $eventTypes = (@($matched.Json.chase.events) | ForEach-Object { $_.event_type }) -join ","
    Assert-Condition ($successEvent.Count -eq 1) "success event was not append-only recorded; events: $eventTypes"

    $escalation = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/vendors/$($vendor.id)/chases" -Headers $headers -Body @{ customer_sender_connector_id = $connectorId; expected_doc_type = "W9"; max_attempts = 1; max_messages_per_week = 3; touch_schedule_days = @(0) }
    Assert-Status $escalation @(201) "escalation chase creation"
    $escalatedTouch = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/chases/$($escalation.Json.chase.id)/touch" -Headers $headers -Body @{ body = "Please send the current W-9 for the open requirement."; approved = $true }
    Assert-Status $escalatedTouch @(200) "escalation chase touch"
    Assert-Condition ([string]$escalatedTouch.Json.chase.status -eq "escalated") "maximum attempts did not escalate the chase"
    $escalationEvent = @(@($escalatedTouch.Json.chase.events) | Where-Object { $_.event_type -eq "chase.escalated" } | Select-Object -First 1)
    Assert-Condition ([bool]$escalationEvent.payload.cc_internal_owner) "escalation did not force the internal-owner CC guardrail"

    Write-Output "P-01 HTTP PASS: 35-rule versioned catalog, 100-case static suite, v1 document acceptance, requirement binding, full COI/endorsement/W-9 verification, supersession, customer-owned sender, approval/negotiation guards, attachment matching, escalation CC, and compliant-and-verified chase success verified over real Compose/PostgreSQL HTTP."
}

$exitCode = 0
try {
    Test-StaticContract
    if ($StaticOnly) {
        Write-Output "P-01 STATIC PASS: taxonomy, 35-rule catalog, reason-code boundary, versioned requirement tables, golden set, and chase guardrails verified."
    } else {
        Start-P01Compose
        Invoke-P01HttpE2E
    }
} catch { Write-Error $_.Exception.Message; $exitCode = 1 } finally { Stop-P01Compose }
if ($exitCode -ne 0) { exit $exitCode }
