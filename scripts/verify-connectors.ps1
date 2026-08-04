[CmdletBinding()]
param([switch]$StaticOnly, [switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$contractPath = Join-Path $repoRoot "tests\connectors\contract.json"
$browserSmokePath = Join-Path $repoRoot "tests\connectors\browser_smoke.py"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-c01"
$backendPort = 18005
$frontendPort = 13005
$postgresPort = 15437
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

function Assert-Condition { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw "C-01 assertion failed: $Message" } }

function Invoke-StorageGuard { if (Test-Path -LiteralPath $storageGuardPath) { & powershell -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { throw "C-01 storage guard failed; Docker usage must remain within the repository budget." } } }

function Invoke-Compose {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $docker.Source @composePrefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "C-01 Compose command failed. Repair the local Compose/WSL boundary and rerun." }
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
        if ($null -eq $response) { throw "C-01 API request failed at $Uri without an HTTP response" }
        $status = [int]$response.StatusCode
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $content = $reader.ReadToEnd()
            $reader.Dispose()
        } catch { $content = $null }
    }
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($content)) { try { $json = $content | ConvertFrom-Json } catch { throw "C-01 API returned a non-JSON response at $Uri" } }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

function Assert-Status { param($Response, [int[]]$Expected, [string]$Action) Assert-Condition ($Expected -contains [int]$Response.Status) "$Action returned HTTP $($Response.Status); response body withheld" }
function Wait-Ready { param([string]$Uri, [string]$Name) for ($attempt = 0; $attempt -lt 90; $attempt++) { try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Uri; if ([int]$response.StatusCode -eq 200) { return } } catch {} Start-Sleep -Milliseconds 1000 }; throw "C-01 $Name did not become ready; inspect the named Compose project logs." }
function New-Headers { param($Login, [string]$WorkspaceId) return @{ Authorization = "Bearer $($Login.access_token)"; "X-Workspace-ID" = $WorkspaceId } }
function New-Login { param([string]$Email, [string]$Name, [string]$Organization, [string]$Workspace) $response = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/auth/dev-login" -Body @{ email = $Email; name = $Name; organization_name = $Organization; workspace_name = $Workspace }; Assert-Status $response @(200) "development login"; return $response.Json }

function Start-C01Compose {
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

function Stop-C01Compose {
    if ($started -and -not $KeepRunning) { try { $null = Invoke-Compose -Arguments @("down", "--remove-orphans"); Invoke-StorageGuard } catch { Write-Warning "C-01 cleanup needs exact project '$projectName' stopped with its Compose env-file." } }
    if ($started -and $KeepRunning) { Write-Output "C-01 services remain running by request; stop only project '$projectName' with its Compose env-file." }
    foreach ($key in $portEnv.Keys) { if ($envHad[$key]) { Set-Item -LiteralPath "Env:$key" -Value $envBackup[$key] } else { Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue } }
}

function Test-StaticContract {
    foreach ($path in @($contractPath, $browserSmokePath, $composeFile, $envFile, $storageGuardPath)) { Assert-Condition (Test-Path -LiteralPath $path -PathType Leaf) "required C-01 path is missing: $path" }
    $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "c01.connectors.v1") "connector contract version is not canonical"
    $service = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\services\connectors.py") -Raw
    $migration = Get-Content -LiteralPath (Join-Path $repoRoot "backend\migrations\versions\0011_connectors_vault.py") -Raw
    $routes = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\api\connector_routes.py") -Raw
    $compose = Get-Content -LiteralPath $composeFile -Raw
    $page = Get-Content -LiteralPath (Join-Path $repoRoot "frontend\src\components\ConnectorsView.tsx") -Raw
    foreach ($marker in @("ConnectorAdapter", "EnvelopeVault", "AESGCM", "redact_untrusted", "verify_webhook_signature", "MCP_TOOL_NOT_ALLOWLISTED", "MCP_APPROVAL_REQUIRED", "EGRESS_NOT_ALLOWED", "RPA_ISOLATION_REQUIRED")) { Assert-Condition ($service -match [regex]::Escape($marker)) "connector service marker is missing: $marker" }
    foreach ($table in @("connectors", "workspace_key_envelopes", "credentials", "mcp_servers", "connector_calls", "credential_access_logs")) { Assert-Condition ($migration -match ('"' + $table + '"')) "connector migration is missing table '$table'" }
    foreach ($route in @("/connectors", "/connectors/{connector_id}/test", "/connectors/{connector_id}/webhook/verify", "/credentials/access-log", "/mcp/servers", "/mcp/servers/{server_id}/tools/call")) { Assert-Condition ($routes -match [regex]::Escape($route)) "connector route marker is missing: $route" }
    foreach ($marker in @("Connect the work, keep the boundary", "OAuth refresh secret", "Pin MCP server", "untrusted", "credential access log")) { Assert-Condition ($page -match [regex]::Escape($marker)) "Connections UI marker is missing: $marker" }
    Assert-Condition ($compose -match "VAULT_KEK_BASE64" -and $compose -match "CONNECTOR_EGRESS_ALLOWLIST") "Compose does not pass connector security configuration"
    $browser = Get-Content -LiteralPath $browserSmokePath -Raw
    Assert-Condition ($browser -match "Connections" -and $browser -match "x-workspace-id") "connector browser smoke markers are missing"
    $forbidden = @('p'+'sql', 'sqli'+'te', 'd'+'ocker exec', 'Invoke'+'-SqlCmd', 'database cli'+'ent')
    foreach ($word in $forbidden) { Assert-Condition (-not ($browser -match [regex]::Escape($word))) "connector browser smoke contains a forbidden direct-storage operation" }
    return $contract
}

function Invoke-C01HttpE2E {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
    $organization = "C01 Verify Org $suffix"
    $workspace = "C01 Verify Workspace $suffix"
    $owner = New-Login -Email "c01-owner-$suffix@example.invalid" -Name "C01 Owner" -Organization $organization -Workspace $workspace
    $workspaceId = [string]$owner.workspace.id
    $headers = New-Headers -Login $owner -WorkspaceId $workspaceId
    $secret = "synthetic-c01-" + [guid]::NewGuid().ToString("N")

    $connector = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors" -Headers $headers -Body @{ name = "C01 sandbox email $suffix"; kind = "email"; config = @{ endpoint = "sandbox://sandbox.local" }; egress_hosts = @("sandbox.local") }
    Assert-Status $connector @(201) "connector creation"
    $connectorId = [string]$connector.Json.connector.id
    $credential = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$connectorId/credentials" -Headers $headers -Body @{ label = "C01 OAuth refresh"; secret = $secret; secret_type = "oauth_refresh_token" }
    Assert-Status $credential @(201) "credential vault write"
    $credentialId = [string]$credential.Json.credential.id
    Assert-Condition ([bool]$credential.Json.credential.ciphertext_present -and -not [bool]$credential.Json.credential.plaintext_exposed) "credential response exposed plaintext or omitted ciphertext proof"
    $serializedCredential = $credential.Json | ConvertTo-Json -Depth 40 -Compress
    Assert-Condition (-not $serializedCredential.Contains($secret)) "credential response contained the synthetic secret"
    $rotated = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$connectorId/credentials/$credentialId/rotate" -Headers $headers -Body @{ secret = ($secret + "-rotated") }
    Assert-Status $rotated @(200) "credential rotation"
    Assert-Condition ([string]$rotated.Json.credential.key_version -eq [string]$credential.Json.credential.key_version) "credential rotation lost the active envelope key version"
    $health = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$connectorId/test" -Headers $headers -Body @{}
    Assert-Status $health @(200) "sandbox connector health"
    Assert-Condition ([bool]$health.Json.healthy -and [string]$health.Json.connector.status -eq "healthy") "sandbox connector did not report healthy"
    $access = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/credentials/access-log" -Headers $headers
    Assert-Status $access @(200) "credential access log"
    Assert-Condition ([int]$access.Json.count -ge 3) "credential create, rotate, and connector-test access events were not recorded"
    Assert-Condition (-not ((($access.Json | ConvertTo-Json -Depth 40 -Compress)).Contains($secret))) "credential access log contained the synthetic secret"

    $webhook = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors" -Headers $headers -Body @{ name = "C01 webhook $suffix"; kind = "webhook"; config = @{ endpoint = "sandbox://sandbox.local" }; egress_hosts = @("sandbox.local") }
    Assert-Status $webhook @(201) "webhook connector creation"
    $webhookId = [string]$webhook.Json.connector.id
    $webhookCredential = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$webhookId/credentials" -Headers $headers -Body @{ label = "C01 webhook signing secret"; secret = $secret; secret_type = "webhook_signing_secret" }
    Assert-Status $webhookCredential @(201) "webhook signing credential"
    $webhookBody = '{"event":"c01"}'
    $webhookTimestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($secret))
    try { $digest = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes("$webhookTimestamp.$webhookBody")) } finally { $hmac.Dispose() }
    $validSignature = "sha256=" + ([System.BitConverter]::ToString($digest).Replace("-", "").ToLowerInvariant())
    $validWebhook = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$webhookId/webhook/verify" -Headers $headers -Body @{ body = $webhookBody; timestamp = $webhookTimestamp; signature = $validSignature }
    Assert-Status $validWebhook @(200) "valid webhook signature"
    Assert-Condition ([bool]$validWebhook.Json.verified) "valid webhook signature was rejected"
    $invalidWebhook = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$webhookId/webhook/verify" -Headers $headers -Body @{ body = $webhookBody; timestamp = $webhookTimestamp; signature = "sha256=invalid" }
    Assert-Status $invalidWebhook @(200) "invalid webhook signature"
    Assert-Condition (-not [bool]$invalidWebhook.Json.verified -and [string]$invalidWebhook.Json.failure_code -eq "WEBHOOK_SIGNATURE_INVALID") "invalid webhook signature did not return the failure taxonomy"

    $badConnector = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors" -Headers $headers -Body @{ name = "C01 blocked egress $suffix"; kind = "rest"; config = @{ endpoint = "https://not-allowed.example.invalid" }; egress_hosts = @("sandbox.local") }
    Assert-Status $badConnector @(201) "blocked-egress connector creation"
    $badHealth = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$($badConnector.Json.connector.id)/test" -Headers $headers -Body @{}
    Assert-Status $badHealth @(200) "blocked-egress connector health"
    Assert-Condition (-not [bool]$badHealth.Json.healthy -and [string]$badHealth.Json.failure.code -eq "EGRESS_NOT_ALLOWED") "egress allow-list failure taxonomy was not surfaced"

    $rpa = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors" -Headers $headers -Body @{ name = "C01 isolated RPA $suffix"; kind = "rpa"; config = @{}; egress_hosts = @() }
    Assert-Status $rpa @(201) "RPA connector creation"
    $rpaHealth = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/connectors/$($rpa.Json.connector.id)/test" -Headers $headers -Body @{}
    Assert-Status $rpaHealth @(200) "RPA isolation health"
    Assert-Condition (-not [bool]$rpaHealth.Json.healthy -and [string]$rpaHealth.Json.failure.code -eq "RPA_ISOLATION_REQUIRED") "RPA was not held behind an explicit isolation contract"

    $metadata = @{ value_at_risk_limit = 100; tools = @(@{ name = "sandbox_search"; read_only = $true; description = "Untrusted search description" }, @{ name = "sandbox_write"; read_only = $false; requires_approval = $true; description = "Untrusted write description" }) }
    $server = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers" -Headers $headers -Body @{ name = "C01 sandbox MCP $suffix"; url = "sandbox://mcp.local"; auth_mode = "none"; server_version = "sandbox-1"; metadata = $metadata; allowed_tools = @("sandbox_search", "sandbox_write"); workflow_version_ids = @("c01-workflow-$suffix"); egress_hosts = @("mcp.local") }
    Assert-Status $server @(201) "MCP server pin"
    $serverId = [string]$server.Json.server.id
    Assert-Condition ([string]$server.Json.server.metadata_hash -match '^[0-9a-f]{64}$') "MCP metadata hash was not pinned"
    $idempotency = "c01-call-$suffix"
    $call = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers/$serverId/tools/call" -Headers $headers -Body @{ tool_name = "sandbox_search"; arguments = @{ query = "C01"; authorization = $secret }; workflow_version_id = "c01-workflow-$suffix"; value_at_risk = 0; approved = $false; idempotency_key = $idempotency }
    Assert-Status $call @(200) "MCP allow-listed call"
    Assert-Condition ([string]$call.Json.call.status -eq "success" -and [bool]$call.Json.call.result_untrusted) "MCP success did not retain the untrusted-output boundary"
    Assert-Condition (-not (($call.Json | ConvertTo-Json -Depth 50 -Compress).Contains($secret))) "MCP call response contained the synthetic secret"
    $repeat = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers/$serverId/tools/call" -Headers $headers -Body @{ tool_name = "sandbox_search"; arguments = @{ query = "C01" }; workflow_version_id = "c01-workflow-$suffix"; value_at_risk = 0; approved = $false; idempotency_key = $idempotency }
    Assert-Status $repeat @(200) "MCP idempotent repeat"
    Assert-Condition ([bool]$repeat.Json.idempotent -and [string]$repeat.Json.call.id -eq [string]$call.Json.call.id) "MCP idempotency key produced a duplicate call"
    $deniedTool = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers/$serverId/tools/call" -Headers $headers -Body @{ tool_name = "not_allow_listed"; arguments = @{}; workflow_version_id = "c01-workflow-$suffix"; idempotency_key = "c01-denied-$suffix" }
    Assert-Status $deniedTool @(403) "MCP tool allow-list denial"
    $approval = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers/$serverId/tools/call" -Headers $headers -Body @{ tool_name = "sandbox_write"; arguments = @{ target = "sandbox" }; workflow_version_id = "c01-workflow-$suffix"; value_at_risk = 500; approved = $false; idempotency_key = "c01-approval-$suffix" }
    Assert-Status $approval @(200) "MCP approval gate"
    Assert-Condition ([bool]$approval.Json.approval_required -and [string]$approval.Json.call.status -eq "approval_required") "MCP value-at-risk approval gate did not halt the write"
    $approved = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers/$serverId/tools/call" -Headers $headers -Body @{ tool_name = "sandbox_write"; arguments = @{ target = "sandbox" }; workflow_version_id = "c01-workflow-$suffix"; value_at_risk = 500; approved = $true; approval_note = "C01 verifier approval"; idempotency_key = "c01-approved-$suffix" }
    Assert-Status $approved @(200) "approved MCP write"
    Assert-Condition ([string]$approved.Json.call.status -eq "success") "approved MCP write did not execute in the sandbox"
    $scopeDenied = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/mcp/servers/$serverId/tools/call" -Headers $headers -Body @{ tool_name = "sandbox_search"; arguments = @{}; workflow_version_id = "other-workflow-$suffix"; idempotency_key = "c01-scope-$suffix" }
    Assert-Status $scopeDenied @(403) "MCP workflow-version scope denial"
    $calls = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/mcp/calls" -Headers $headers
    Assert-Status $calls @(200) "MCP call audit read"
    Assert-Condition ([int]$calls.Json.count -ge 5) "MCP call log did not retain success, denied, approval, and scope events"
    Assert-Condition (-not (($calls.Json | ConvertTo-Json -Depth 60 -Compress).Contains($secret))) "MCP call log contained the synthetic secret"

    $auditorEmail = "c01-auditor-$suffix@example.invalid"
    $invite = Invoke-JsonBoundary -Method POST -Uri "$apiBase/api/workspaces/$workspaceId/members" -Headers $headers -Body @{ email = $auditorEmail; name = "C01 Auditor"; role = "auditor" }
    Assert-Status $invite @(200, 201) "auditor membership"
    $auditor = New-Login -Email $auditorEmail -Name "C01 Auditor" -Organization $organization -Workspace $workspace
    $auditorHeaders = New-Headers -Login $auditor -WorkspaceId $workspaceId
    $auditorLog = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/credentials/access-log" -Headers $auditorHeaders
    Assert-Status $auditorLog @(200) "auditor credential access read"
    $other = New-Login -Email "c01-other-$suffix@example.invalid" -Name "C01 Other" -Organization "C01 Other Org $suffix" -Workspace "C01 Other Workspace $suffix"
    $otherHeaders = New-Headers -Login $other -WorkspaceId ([string]$other.workspace.id)
    $hidden = Invoke-JsonBoundary -Method GET -Uri "$apiBase/api/connectors/$connectorId" -Headers $otherHeaders
    Assert-Status $hidden @(404, 403) "connector cross-workspace isolation"
    Write-Output "C-01 HTTP PASS: sandbox adapters, ciphertext-only vault, rotation, access log, egress/RPA guards, pinned MCP metadata, allow-list/workflow scope, idempotency, redaction, approval gate, auditor access, and workspace isolation verified."
}

function Invoke-C01Browser {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the Connections browser smoke"
    $output = @(& $python.Source $browserSmokePath --frontend-url $frontendBase 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "C-01 browser smoke failed; repair the live Connections boundary and rerun." }
    Write-Output "C-01 browser PASS: authenticated Connections UI, vault-safe credential flow, sandbox health, pinned MCP call, and scoped headers verified."
}

$exitCode = 0
try {
    $null = Test-StaticContract
    if ($StaticOnly) {
        Write-Output "C-01 STATIC PASS: connector contract, migration, vault/MCP guards, API routes, Compose security config, UI, and browser smoke verified."
    } else {
        Start-C01Compose
        Invoke-C01HttpE2E
        Invoke-C01Browser
        Write-Output "C-01 E2E PASS: real Compose/PostgreSQL HTTP, sandbox, vault, MCP, and browser evidence completed."
    }
} catch {
    Write-Error $_.Exception.Message
    $exitCode = 1
} finally { Stop-C01Compose }
if ($exitCode -ne 0) { exit $exitCode }
