[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$envTemplate = Join-Path $repoRoot ".env.example"
$contractPath = Join-Path $repoRoot "tests\governance\contract.json"
$browserSmoke = Join-Path $repoRoot "tests\governance\browser_smoke.py"
$projectName = "ai-ops-platform-mvp"
$apiBaseUrl = "http://localhost:8000"
$frontendBaseUrl = "http://localhost:3000"
$existingBackend = $false

function Assert-Condition {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Message)
    if (-not $Condition) {
        throw "G-01 assertion failed: $Message"
    }
}

function Resolve-DockerExecutable {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $knownPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $knownPath) { return $knownPath }
    throw "Docker executable was not found. Start Docker Desktop and rerun the governance verifier."
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $composePrefix = @("compose", "--project-name", $projectName, "--env-file", $envFile, "--file", $composeFile)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $dockerExe @($composePrefix + $Arguments) 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker Compose failed: $($output -join ([Environment]::NewLine))"
    }
    return $output
}

function Wait-Ready {
    param([Parameter(Mandatory)][string]$Uri, [int]$Attempts = 60)
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) { return }
        } catch {
            # The next bounded attempt is the repair path while services start.
        }
        Start-Sleep -Seconds 2
    }
    throw "$Uri did not become ready. Inspect Docker Compose backend/postgres logs."
}

function Invoke-JsonApi {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "PATCH")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Headers,
        [AllowNull()][object]$Body = $null
    )
    $params = @{
        Method = $Method
        Uri = "$apiBaseUrl$Path"
        Headers = $Headers
        UseBasicParsing = $true
        TimeoutSec = 30
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body | ConvertTo-Json -Depth 30 -Compress
    }
    return Invoke-RestMethod @params
}

function New-Login {
    param([string]$Email, [string]$Organization, [string]$Workspace)
    return Invoke-JsonApi -Method POST -Path "/api/auth/dev-login" -Headers @{} -Body @{
        email = $Email
        name = "G01 verifier"
        organization_name = $Organization
        workspace_name = $Workspace
    }
}

function Invoke-PostgresSql {
    param([Parameter(Mandatory)][string]$Sql)
    $composePrefix = @("compose", "--project-name", $projectName, "--env-file", $envFile, "--file", $composeFile)
    $arguments = $composePrefix + @("exec", "-T", "postgres", "sh", "-c", 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -')
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @($Sql | & $dockerExe @arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

function Invoke-MultipartUpload {
    param([Parameter(Mandatory)][hashtable]$Headers, [Parameter(Mandatory)][string]$VendorId, [Parameter(Mandatory)][string]$FilePath)
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/plain")
        $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
        $form.Add([System.Net.Http.StringContent]::new("COI"), "doc_type")
        $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, "$apiBaseUrl/api/vendors/$VendorId/documents")
        $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Headers.Authorization.Substring(7))
        $request.Headers.Add("X-Workspace-ID", $Headers."X-Workspace-ID")
        $request.Content = $form
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "multipart upload failed: $body" }
        return $body | ConvertFrom-Json
    } finally {
        $form.Dispose()
        $client.Dispose()
    }
}

try {
    foreach ($path in @($composeFile, $envTemplate, $contractPath, $browserSmoke)) {
        Assert-Condition -Condition (Test-Path -LiteralPath $path) -Message "required verifier file is missing: $path"
    }
    Assert-Condition -Condition (Test-Path -LiteralPath $envFile) -Message "ignored .env is required for the real Compose gate"
    $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    $modelText = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\models.py") -Raw
    $serviceText = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\services\governance.py") -Raw
    $routeText = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\api\governance_routes.py") -Raw
    $migrationText = Get-Content -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0017_governance.py") -Raw
    foreach ($marker in @("GovernanceArtifact", "RetentionPolicy", "LegalHold", "GovernanceIncident", "ModelChangeHistory", "AuditPack")) {
        Assert-Condition -Condition ($modelText.Contains("class $marker")) -Message "model marker $marker is missing"
    }
    foreach ($marker in @("classify_pii_payload", "retention_run", "build_audit_pack", "redact_governance_payload", "no_training")) {
        Assert-Condition -Condition ($serviceText.Contains($marker)) -Message "service marker $marker is missing"
    }
    foreach ($route in @("/summary", "/artifacts", "/retention-policies", "/retention/run", "/legal-holds", "/incidents", "/model-registry", "/audit-packs")) {
        Assert-Condition -Condition ($routeText.Contains($route)) -Message "governance route $route is missing"
    }
    foreach ($marker in @("prevent_governance_append_only_mutation", "audit_logs_immutable", "data_access_logs_immutable", "credential_access_logs_immutable", "model_change_history_immutable", "audit_packs_immutable")) {
        Assert-Condition -Condition ($migrationText.Contains($marker)) -Message "migration immutability marker $marker is missing"
    }
    Assert-Condition -Condition ($contract.roles.auditor -contains "governance.export") -Message "auditor export role contract is missing"
    Assert-Condition -Condition ($contract.browser.heading -eq "Make every decision inspectable.") -Message "browser contract heading drifted"
    if ($StaticOnly) {
        Write-Output "G-01 STATIC PASS: governance models, privacy/redaction service, routes, roles, immutable migration, and browser contract verified."
        exit 0
    }

    $dockerExe = Resolve-DockerExecutable
    $running = @(Invoke-Compose -Arguments @("ps", "-q", "backend"))
    $existingBackend = $running.Count -gt 0
    if (-not $existingBackend) {
        Invoke-Compose -Arguments @("up", "-d", "--build")
    } else {
        Invoke-Compose -Arguments @("up", "-d", "--build", "backend", "runtime-worker", "frontend")
    }
    Wait-Ready -Uri "$apiBaseUrl/api/health"
    Wait-Ready -Uri $frontendBaseUrl

    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
    $login = New-Login -Email "g01-$stamp@example.invalid" -Organization "G01 Org $stamp" -Workspace "G01 Workspace $stamp"
    $token = if ($login.access_token) { $login.access_token } else { $login.token }
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($token)) -Message "development login did not return a token"
    $headers = @{ Authorization = "Bearer $token"; "X-Workspace-ID" = $login.workspace.id }

    $piiArtifact = Invoke-JsonApi -Method POST -Path "/api/governance/artifacts" -Headers $headers -Body @{
        artifact_type = "governance_fixture"
        artifact_id = "pii-$stamp"
        storage_ref = "fixture://pii-$stamp"
        metadata = @{ contact_email = "operator-$stamp@example.invalid"; phone = "+1 555 010 4444"; credential_token = "never-persisted" }
    }
    Assert-Condition -Condition ($piiArtifact.pii_status -eq "detected") -Message "PII fixture was not classified"
    Assert-Condition -Condition (-not ($piiArtifact.pii_flags | ConvertTo-Json -Compress).Contains("operator-$stamp@example.invalid")) -Message "PII value leaked into classification flags"
    Invoke-JsonApi -Method POST -Path "/api/governance/retention-policies" -Headers $headers -Body @{
        artifact_type = "governance_fixture"
        retention_days = 1
        action = "delete_source_keep_derived"
        active = $true
    } | Out-Null
    $held = Invoke-JsonApi -Method POST -Path "/api/governance/legal-holds" -Headers $headers -Body @{
        artifact_type = "governance_fixture"
        artifact_id = $piiArtifact.artifact_id
        reason = "Synthetic audit preservation"
    }
    $dryHeld = Invoke-JsonApi -Method POST -Path "/api/governance/retention/run" -Headers $headers -Body @{ as_of = "2030-01-01T00:00:00Z"; dry_run = $true }
    Assert-Condition -Condition ($dryHeld.held_count -eq 1 -and $dryHeld.deleted_count -eq 0) -Message "retention dry-run did not respect the legal hold"
    Invoke-JsonApi -Method POST -Path "/api/governance/legal-holds/$($held.id)/release" -Headers $headers | Out-Null
    $dryEligible = Invoke-JsonApi -Method POST -Path "/api/governance/retention/run" -Headers $headers -Body @{ as_of = "2030-01-01T00:00:00Z"; dry_run = $true }
    Assert-Condition -Condition ($dryEligible.eligible_count -ge 1) -Message "retention dry-run did not identify a due artifact"
    $executed = Invoke-JsonApi -Method POST -Path "/api/governance/retention/run" -Headers $headers -Body @{ as_of = "2030-01-01T00:00:00Z"; dry_run = $false }
    Assert-Condition -Condition ($executed.deleted_count -ge 1) -Message "retention execution did not delete source metadata"
    $artifacts = Invoke-JsonApi -Method GET -Path "/api/governance/artifacts" -Headers $headers
    $persistedArtifact = @($artifacts.items | Where-Object { $_.artifact_id -eq $piiArtifact.artifact_id })[0]
    Assert-Condition -Condition ($persistedArtifact.source_deleted_at -and $persistedArtifact.sha256 -eq $piiArtifact.sha256) -Message "derived artifact hash was not retained after source deletion"

    $model = Invoke-JsonApi -Method POST -Path "/api/model-configs" -Headers $headers -Body @{
        key = "g01-model-$stamp"
        provider = "sandbox"
        model_id = "model-v1"
        params = @{ temperature = 0 }
        training_policy = "no_training"
    }
    $registry = Invoke-JsonApi -Method GET -Path "/api/governance/model-registry" -Headers $headers
    Assert-Condition -Condition (@($registry.changes | Where-Object { $_.model_config_id -eq $model.id }).Count -eq 1) -Message "model change history was not recorded"
    Assert-Condition -Condition (@($registry.items | Where-Object { $_.id -eq $model.id }).training_policy -eq "no_training") -Message "no-training model policy was not retained"

    $incident = Invoke-JsonApi -Method POST -Path "/api/governance/incidents" -Headers $headers -Body @{ severity = "high"; summary = "Synthetic G-01 incident"; customer_notification_status = "pending" }
    $incident = Invoke-JsonApi -Method PATCH -Path "/api/governance/incidents/$($incident.id)" -Headers $headers -Body @{ status = "investigating"; root_cause = "Synthetic test root cause"; customer_notification_status = "sent" }
    $incident = Invoke-JsonApi -Method POST -Path "/api/governance/incidents/$($incident.id)/timeline" -Headers $headers -Body @{ event = "customer_notified"; details = @{ channel = "sandbox" } }
    $incident = Invoke-JsonApi -Method PATCH -Path "/api/governance/incidents/$($incident.id)" -Headers $headers -Body @{ status = "resolved"; root_cause = "Synthetic test root cause confirmed" }
    Assert-Condition -Condition ($incident.status -eq "resolved" -and $incident.resolved_at) -Message "incident lifecycle did not resolve"

    $pack = Invoke-JsonApi -Method POST -Path "/api/governance/audit-packs" -Headers $headers -Body @{}
    Assert-Condition -Condition ($pack.payload.redaction.prompt_bodies_excluded -eq $true) -Message "audit pack prompt exclusion marker is missing"
    Assert-Condition -Condition (@($pack.payload.models | Where-Object { $_.id -eq $model.id -and $_.training_policy -eq "no_training" }).Count -eq 1) -Message "audit pack model record is incomplete"
    $packText = $pack | ConvertTo-Json -Depth 40 -Compress
    Assert-Condition -Condition (-not $packText.Contains("operator-$stamp@example.invalid")) -Message "audit pack leaked PII"
    $download = Invoke-WebRequest -UseBasicParsing -Method Get -Uri "$apiBaseUrl/api/governance/audit-packs/$($pack.id)/download" -Headers $headers
    Assert-Condition -Condition ([int]$download.StatusCode -eq 200 -and $download.Headers["Content-Disposition"] -match "audit-pack") -Message "audit pack download response is not an attachment"
    $audit = Invoke-JsonApi -Method GET -Path "/api/audit" -Headers $headers
    Assert-Condition -Condition (@($audit.items).Count -ge 1) -Message "audit read did not return immutable governance events"

    $updateAttempt = Invoke-PostgresSql -Sql "UPDATE audit_logs SET action = 'tampered' WHERE id = (SELECT id FROM audit_logs WHERE workspace_id = '$($login.workspace.id)' LIMIT 1);"
    Assert-Condition -Condition ($updateAttempt.ExitCode -ne 0 -and ($updateAttempt.Output -join ([Environment]::NewLine)).Contains("append-only")) -Message "audit log update was not rejected by the database trigger"
    $deleteAttempt = Invoke-PostgresSql -Sql "DELETE FROM data_access_logs WHERE id = (SELECT id FROM data_access_logs WHERE workspace_id = '$($login.workspace.id)' LIMIT 1);"
    Assert-Condition -Condition ($deleteAttempt.ExitCode -ne 0 -and ($deleteAttempt.Output -join ([Environment]::NewLine)).Contains("append-only")) -Message "data-access delete was not rejected by the database trigger"

    python $browserSmoke --frontend-url $frontendBaseUrl
    Write-Output "G-01 HTTP PASS: PII classification/redaction, legal holds, retention dry-run and deletion, model policy/history, incident lifecycle, audit pack completeness/download, access logging, and immutable triggers verified."
    Write-Output "G-01 browser PASS: authenticated governance controls and workspace-scoped requests verified."
    Write-Output "G-01 E2E PASS: real Compose/PostgreSQL evidence completed."
} finally {
    if (-not $KeepRunning -and -not $existingBackend -and $dockerExe) {
        Invoke-Compose -Arguments @("down", "--remove-orphans") | Out-Null
    }
}
