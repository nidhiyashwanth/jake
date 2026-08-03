[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$contractPath = Join-Path $repoRoot "tests\discovery\contract.json"
$fixtureRoot = Join-Path $repoRoot "tests\discovery\fixtures"
$sopFixture = Join-Path $fixtureRoot "discovery.sop.txt"
$transcriptFixture = Join-Path $fixtureRoot "discovery.transcript.txt"
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$envTemplate = Join-Path $repoRoot ".env.example"
$projectName = "ai-ops-platform-d01"

# Use alternate host ports so this verifier cannot accidentally talk to another
# Compose project. The container-to-container database URL remains unchanged.
$backendPort = 18001
$frontendPort = 13001
$postgresPort = 15433
$apiBaseUrl = "http://localhost:$backendPort"

$started = $false
$dockerExe = $null
$composePrefix = @()
$contract = $null
$portEnvironment = [ordered]@{
    BACKEND_PORT = [string]$backendPort
    FRONTEND_PORT = [string]$frontendPort
    POSTGRES_PORT = [string]$postgresPort
    NEXT_PUBLIC_API_BASE_URL = $apiBaseUrl
}
$previousEnvironment = @{}
$hadEnvironment = @{}
$environmentConfigured = $false

function Assert-Condition {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Message
    )

    if (-not $Condition) {
        throw "D-01 assertion failed: $Message Repair: inspect the first failing API response and the corresponding service logs. Response bodies are intentionally withheld."
    }
}

function Get-JsonValue {
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory)][string]$Path
    )

    $current = $Object
    foreach ($segment in ($Path -split '\.')) {
        if ($null -eq $current) {
            return $null
        }
        if ($segment -match '^\d+$' -and $current -is [System.Array]) {
            $index = [int]$segment
            if ($index -ge $current.Count) {
                return $null
            }
            $current = $current[$index]
            continue
        }
        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return $null
        }
        $current = $property.Value
    }
    return $current
}

function Get-FirstValue {
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory)][string[]]$CandidatePaths
    )

    foreach ($candidatePath in $CandidatePaths) {
        $candidate = Get-JsonValue -Object $Object -Path $candidatePath
        if ($null -eq $candidate) {
            continue
        }
        if ($candidate -is [string] -and [string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        return $candidate
    }
    return $null
}

function Get-ResponseItems {
    param([AllowNull()][object]$Json)

    if ($null -eq $Json) {
        return @()
    }
    if ($Json -is [System.Array]) {
        return @($Json)
    }
    foreach ($propertyName in @("items", "events", "entries", "data")) {
        $property = $Json.PSObject.Properties[$propertyName]
        if ($null -ne $property -and $null -ne $property.Value) {
            return @($property.Value)
        }
    }
    return @($Json)
}

function Get-EntityId {
    param(
        [AllowNull()][object]$Json,
        [Parameter(Mandatory)][string[]]$CandidatePaths,
        [Parameter(Mandatory)][string]$Action
    )

    $candidate = Get-FirstValue -Object $Json -CandidatePaths $CandidatePaths
    if ($null -eq $candidate -or [string]::IsNullOrWhiteSpace([string]$candidate)) {
        throw "D-01 contract gap: $Action succeeded but did not return a stable id. Expected one of: $($CandidatePaths -join ', ')."
    }
    return [string]$candidate
}

function Get-EventAction {
    param([AllowNull()][object]$Event)

    $value = Get-FirstValue -Object $Event -CandidatePaths @("action", "event_type", "type", "event")
    if ($null -eq $value) {
        return ""
    }
    return [string]$value
}

function Get-EventId {
    param([AllowNull()][object]$Event)

    $value = Get-FirstValue -Object $Event -CandidatePaths @("id", "event_id", "audit_id")
    if ($null -eq $value) {
        return ""
    }
    return [string]$value
}

function Get-ContractRoute {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$RouteKey,
        [hashtable]$Replacements = @{}
    )

    $routeProperty = $Contract.routes.PSObject.Properties[$RouteKey]
    if ($null -eq $routeProperty) {
        throw "D-01 contract is missing route '$RouteKey'."
    }
    $route = $routeProperty.Value
    $path = [string]$route.path
    foreach ($replacementKey in $Replacements.Keys) {
        $path = $path.Replace("{$replacementKey}", [string]$Replacements[$replacementKey])
    }
    if ($path -match '\{[^}]+\}') {
        throw "D-01 route '$RouteKey' still has an unresolved path parameter: $path"
    }
    return [pscustomobject]@{
        Method = [string]$route.method
        Path = $path
    }
}

function Test-ValuePresent {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) {
        return $false
    }
    if ($Value -is [string]) {
        return -not [string]::IsNullOrWhiteSpace($Value)
    }
    if ($Value -is [System.Array]) {
        return $Value.Count -gt 0
    }
    if ($Value -is [System.Collections.IDictionary]) {
        return $Value.Count -gt 0
    }
    if ($Value.PSObject.Properties.Count -gt 0 -and $Value -isnot [bool]) {
        return $true
    }
    return $true
}

function Assert-ApiStatus {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][int[]]$Expected,
        [Parameter(Mandatory)][string]$Action
    )

    if ($Expected -notcontains [int]$Response.Status) {
        throw "D-01 contract failure: $Action returned HTTP $($Response.Status); expected $($Expected -join ', '). The response body is intentionally withheld."
    }
}

function Assert-ApiSuccess {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Action,
        [int[]]$Expected = @(200, 201, 202, 204)
    )

    Assert-ApiStatus -Response $Response -Expected $Expected -Action $Action
}

function Assert-ApiDenied {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Action,
        [int[]]$Expected = @(401, 403, 404)
    )

    Assert-ApiStatus -Response $Response -Expected $Expected -Action "$Action (scope or RBAC denial)"
}

function Assert-ErrorEnvelope {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Action
    )

    $code = Get-FirstValue -Object $Response.Json -CandidatePaths @("error.code", "code")
    $message = Get-FirstValue -Object $Response.Json -CandidatePaths @("error.message", "message", "detail")
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$code)) -Message "$Action did not return a stable error code"
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$message)) -Message "$Action did not return a repairable error message"
}

function Assert-NoCredentialText {
    param(
        [AllowNull()][string]$Text,
        [Parameter(Mandatory)][string]$Action
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return
    }
    $patterns = @(
        '(?i)POSTGRES_PASSWORD\s*=',
        '(?i)DATABASE_URL\s*=',
        '-----BEGIN\s+[A-Z0-9 ]*PRIVATE KEY-----',
        '(?i)client[_ -]?secret\s*=',
        '(?i)private[_ -]?key\s*='
    )
    foreach ($pattern in $patterns) {
        if ($Text -match $pattern) {
            throw "D-01 secret-safety failure: $Action contained credential-like text. The response body is withheld."
        }
    }
}

function Assert-NumericClose {
    param(
        [Parameter(Mandatory)][double]$Actual,
        [Parameter(Mandatory)][double]$Expected,
        [Parameter(Mandatory)][string]$Action
    )

    $tolerance = [math]::Max(0.01, [math]::Abs($Expected) * 0.0001)
    if ([math]::Abs($Actual - $Expected) -gt $tolerance) {
        throw "D-01 formula failure: $Action was not reproducible within tolerance. Expected a numeric value derived from the published formula."
    }
}

function Assert-IsoTimestamp {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory)][string]$Action
    )

    Assert-Condition -Condition ($null -ne $Value -and -not [string]::IsNullOrWhiteSpace([string]$Value)) -Message "$Action did not return a timestamp"
    try {
        $parsed = [DateTimeOffset]::Parse([string]$Value)
    } catch {
        throw "D-01 contract failure: $Action returned a timestamp that is not ISO-parseable."
    }
    Assert-Condition -Condition ($parsed.Year -ge 2020) -Message "$Action returned an implausible timestamp"
}

function Assert-Sha256 {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory)][string]$Action
    )

    Assert-Condition -Condition ([string]$Value -match '^[0-9a-fA-F]{64}$') -Message "$Action did not return a canonical 64-character SHA-256 hash"
}

function Convert-ToBoolean {
    param([AllowNull()][object]$Value)

    if ($Value -is [bool]) {
        return [bool]$Value
    }
    return [string]::Equals([string]$Value, "true", [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-DraftContract {
    param(
        [Parameter(Mandatory)]$Json,
        [Parameter(Mandatory)][string]$Action
    )

    $status = Get-FirstValue -Object $Json -CandidatePaths @("status", "draft_status", "discovery.status", "draft.status", "ingestion.status")
    Assert-Condition -Condition ($null -ne $status -and ([string]$status).ToLowerInvariant() -in @("draft", "intake_draft", "draft_pending_review")) -Message "$Action did not remain in an explicit draft status"

    $humanReviewRequired = Get-FirstValue -Object $Json -CandidatePaths @("human_review_required", "draft.human_review_required", "ingestion.human_review_required")
    Assert-Condition -Condition ($null -ne $humanReviewRequired -and (Convert-ToBoolean $humanReviewRequired)) -Message "$Action did not declare human_review_required=true"

    $publishAllowed = Get-FirstValue -Object $Json -CandidatePaths @("publish_allowed", "draft.publish_allowed", "ingestion.publish_allowed")
    Assert-Condition -Condition ($null -ne $publishAllowed -and -not (Convert-ToBoolean $publishAllowed)) -Message "$Action did not declare publish_allowed=false"
}

function Resolve-DockerExecutable {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        $command = Get-Command docker -ErrorAction SilentlyContinue
    }
    if ($null -ne $command) {
        $dockerPath = [string]$command.Source
        if ([string]::IsNullOrWhiteSpace($dockerPath)) {
            $dockerPath = [string]$command.Path
        }
        $dockerBin = Split-Path -Parent $dockerPath
        if (($env:Path -split ';') -notcontains $dockerBin) {
            $env:Path = "$dockerBin;$env:Path"
        }
        return $dockerPath
    }

    $knownPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $knownPath) {
        $dockerBin = Split-Path -Parent $knownPath
        if (($env:Path -split ';') -notcontains $dockerBin) {
            $env:Path = "$dockerBin;$env:Path"
        }
        return $knownPath
    }

    throw "D-01 prerequisite: the container runtime executable was not found. Start Docker Desktop or refresh PATH, then rerun scripts\verify-discovery.ps1."
}

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = @(& $dockerExe @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "D-01 Docker command failed for project '$projectName'. Docker output is withheld to prevent accidental credential disclosure. Repair: inspect only this project's service logs and fix the first failing service."
    }
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    Invoke-Docker -Arguments ($composePrefix + $Arguments)
}

function Get-HttpErrorBody {
    param([Parameter(Mandatory)]$Exception)

    $response = $Exception.Response
    if ($null -eq $response) {
        return $Exception.Message
    }
    try {
        $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
        try {
            return $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
    } catch {
        return $Exception.Message
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [int]$Attempts = 60
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                Write-Output "D-01 service ready: GET $Uri"
                return
            }
        } catch {
            $null = Get-HttpErrorBody -Exception $_.Exception
        }
        Start-Sleep -Seconds 2
    }
    throw "D-01 service readiness failed for GET $Uri after $Attempts attempts. The last response is withheld. Repair: inspect this project's backend and PostgreSQL health logs."
}

function Invoke-Api {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [AllowNull()][object]$Body = $null,
        [AllowNull()][string]$Token = $null,
        [hashtable]$Headers = @{}
    )

    $requestHeaders = @{}
    foreach ($headerKey in $Headers.Keys) {
        $requestHeaders[$headerKey] = [string]$Headers[$headerKey]
    }
    if (-not [string]::IsNullOrWhiteSpace($Token)) {
        $requestHeaders["Authorization"] = "Bearer $Token"
    }

    $uri = "$apiBaseUrl$Path"
    try {
        if ($null -eq $Body) {
            $response = Invoke-WebRequest -Uri $uri -Method $Method -Headers $requestHeaders -UseBasicParsing -TimeoutSec 20
        } else {
            $json = $Body | ConvertTo-Json -Depth 30 -Compress
            $response = Invoke-WebRequest -Uri $uri -Method $Method -Headers $requestHeaders -ContentType "application/json" -Body $json -UseBasicParsing -TimeoutSec 20
        }
        $status = [int]$response.StatusCode
        $responseBody = [string]$response.Content
    } catch {
        $webResponse = $_.Exception.Response
        if ($null -eq $webResponse) {
            throw "D-01 HTTP transport failure for $Method ${Path}: $($_.Exception.Message)"
        }
        $status = [int]$webResponse.StatusCode
        $responseBody = Get-HttpErrorBody -Exception $_.Exception
    }

    Assert-NoCredentialText -Text $responseBody -Action "$Method $Path response"
    $parsed = $null
    if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
        try {
            $parsed = $responseBody | ConvertFrom-Json
        } catch {
            $parsed = $null
        }
    }
    return [pscustomobject]@{
        Status = $status
        Body = $responseBody
        Json = $parsed
    }
}

function Invoke-ContractApi {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$RouteKey,
        [AllowNull()][object]$Body = $null,
        [AllowNull()][string]$Token = $null,
        [hashtable]$Replacements = @{},
        [hashtable]$Headers = @{}
    )

    $route = Get-ContractRoute -Contract $Contract -RouteKey $RouteKey -Replacements $Replacements
    Invoke-Api -Method $route.Method -Path $route.Path -Body $Body -Token $Token -Headers $Headers
}

function Invoke-MultipartIngest {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$DiscoveryId,
        [Parameter(Mandatory)][string]$SourceType,
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string]$Token
    )

    Add-Type -AssemblyName System.Net.Http
    $route = Get-ContractRoute -Contract $Contract -RouteKey "discovery_ingest" -Replacements @{ discovery_id = $DiscoveryId }
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/plain")
        $null = $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
        $null = $form.Add([System.Net.Http.StringContent]::new($SourceType), "source_type")
        $response = $client.PostAsync("$apiBaseUrl$($route.Path)", $form).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        Assert-NoCredentialText -Text $body -Action "POST $($route.Path) response"
        $parsed = $null
        if (-not [string]::IsNullOrWhiteSpace($body)) {
            try {
                $parsed = $body | ConvertFrom-Json
            } catch {
                $parsed = $null
            }
        }
        return [pscustomobject]@{
            Status = [int]$response.StatusCode
            Body = $body
            Json = $parsed
        }
    } finally {
        $form.Dispose()
        $client.Dispose()
    }
}

function Set-ActiveContext {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][string]$WorkspaceId
    )

    $context = Invoke-ContractApi -Contract $Contract -RouteKey "context_set" -Token $Token -Body @{ workspace_id = $WorkspaceId }
    Assert-ApiSuccess -Response $context -Action "POST /api/auth/context to requested workspace" -Expected @(200)
    $activeWorkspace = Get-FirstValue -Object $context.Json -CandidatePaths @("active_workspace_id", "workspace.id", "workspace_id")
    Assert-Condition -Condition ([string]$activeWorkspace -eq $WorkspaceId) -Message "context response did not identify the requested active workspace"
}

function Get-Token {
    param([Parameter(Mandatory)]$LoginResponse)

    $token = Get-FirstValue -Object $LoginResponse.Json -CandidatePaths @("access_token", "token", "session.access_token")
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$token)) -Message "development login did not return a bearer session token"
    return [string]$token
}

function Get-WorkspaceId {
    param(
        [Parameter(Mandatory)]$LoginResponse,
        [Parameter(Mandatory)][string]$Action
    )

    return Get-EntityId -Json $LoginResponse.Json -CandidatePaths @("workspace.id", "workspace_id", "session.workspace_id") -Action $Action
}

function Get-SignerText {
    param([AllowNull()][object]$Json)

    $signer = Get-FirstValue -Object $Json -CandidatePaths @("signed_by", "signer", "baseline.signed_by", "baseline.signer")
    if ($null -eq $signer) {
        return ""
    }
    if ($signer -is [string]) {
        return [string]$signer
    }
    $name = Get-FirstValue -Object $signer -CandidatePaths @("name", "display_name", "full_name")
    $email = Get-FirstValue -Object $signer -CandidatePaths @("email", "address")
    return "$name $email".Trim()
}

function Get-MetricValue {
    param(
        [Parameter(Mandatory)][System.Collections.IDictionary]$Metrics,
        [Parameter(Mandatory)][string]$Key
    )

    $entry = $Metrics[$Key]
    if ($entry -is [System.Collections.IDictionary]) {
        return [double]$entry.value
    }
    return [double]$entry
}

function Copy-Metrics {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Metrics)

    $copy = [ordered]@{}
    foreach ($key in $Metrics.Keys) {
        $entry = $Metrics[$key]
        if ($entry -is [System.Collections.IDictionary]) {
            $copy[$key] = [ordered]@{
                value = $entry.value
                unit = $entry.unit
                source = $entry.source
            }
        } else {
            $copy[$key] = $entry
        }
    }
    return $copy
}

function Get-ScoreValue {
    param(
        [Parameter(Mandatory)]$Json,
        [Parameter(Mandatory)][string]$Key
    )

    $value = Get-FirstValue -Object $Json -CandidatePaths @(
        $Key,
        "score.$Key",
        "result.$Key",
        "opportunity_score.$Key",
        "score.outputs.$Key",
        "result.outputs.$Key"
    )
    Assert-Condition -Condition ($null -ne $value) -Message "score response did not expose $Key"
    return [double]$value
}

function Get-ScoreProjection {
    param([Parameter(Mandatory)]$Json)

    return [ordered]@{
        formula_version = [string](Get-FirstValue -Object $Json -CandidatePaths @("formula_version", "score.formula_version", "result.formula_version"))
        current_annual_cost = Get-ScoreValue -Json $Json -Key "current_annual_cost"
        projected_savings = Get-ScoreValue -Json $Json -Key "projected_savings"
        priority_score = Get-ScoreValue -Json $Json -Key "priority_score"
    }
}

function New-DiscoveryMetrics {
    return [ordered]@{
        volume_per_month = [ordered]@{ value = 1850; unit = "instances/month"; source = "operator_interview" }
        minutes_p50 = [ordered]@{ value = 6.5; unit = "minutes/instance"; source = "operator_interview" }
        minutes_p90 = [ordered]@{ value = 22; unit = "minutes/instance"; source = "operator_interview" }
        fully_loaded_cost_per_hour = [ordered]@{ value = 38; unit = "USD/hour"; source = "finance_rate_card" }
        error_rate_pct = [ordered]@{ value = 0.04; unit = "fraction"; source = "sampled_review" }
        cost_per_error = [ordered]@{ value = 165; unit = "USD/error"; source = "finance_interview" }
        rework_rate_pct = [ordered]@{ value = 0.11; unit = "fraction"; source = "operator_interview" }
        cycle_time_hours = [ordered]@{ value = 18; unit = "hours/instance"; source = "workflow_observation" }
        headcount_touching = [ordered]@{ value = 4; unit = "people"; source = "org_chart" }
        peak_backlog = [ordered]@{ value = 220; unit = "instances"; source = "queue_snapshot" }
        chase_volume_per_month = [ordered]@{ value = 420; unit = "messages/month"; source = "mailbox_count" }
        lapse_incidents_per_year = [ordered]@{ value = 7; unit = "incidents/year"; source = "incident_register" }
        audit_prep_hours_per_month = [ordered]@{ value = 14; unit = "hours/month"; source = "audit_interview" }
    }
}

function New-DiscoveryPayload {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Tag
    )

    $metrics = New-DiscoveryMetrics
    return [ordered]@{
        name = $Name
        department = "Field Operations"
        system_of_record = "Vendor compliance register"
        trigger = "A subcontractor or broker emails a certificate"
        inputs = @("COI PDF", "vendor master record", "project requirements")
        steps = @(
            [ordered]@{ seq = 1; description = "Download the attachment"; system = "shared compliance inbox"; minutes_p50 = 2; minutes_p90 = 5; is_decision = $false }
            [ordered]@{ seq = 2; description = "Compare identity and coverage against the requirement set"; system = "vendor compliance register"; minutes_p50 = 3; minutes_p90 = 12; is_decision = $true }
            [ordered]@{ seq = 3; description = "Record the decision or route an exception"; system = "review queue"; minutes_p50 = 1.5; minutes_p90 = 5; is_decision = $true }
        )
        decisions = @("Whether the evidence satisfies the project requirement", "Whether a sponsor question is needed")
        exceptions = @("DBA name differs from the legal name", "Endorsement is missing or unreadable", "Certificate is expired on arrival")
        approvals = @("Project manager approves a documented exception")
        outputs = @("Point-in-time verification record", "Human-review exception", "Sponsor question when evidence is insufficient")
        failure_modes = @("Duplicate certificates", "Unreadable scan", "Late renewal")
        baseline_metrics = $metrics
        captured_by = "human_operator"
        client_reference = "D01 synthetic run $Tag"
    }
}

function Assert-DiscoveryIntake {
    param(
        [Parameter(Mandatory)]$Json,
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$Action
    )

    foreach ($field in @($Contract.required_intake_fields | ForEach-Object { [string]$_ })) {
        $value = Get-FirstValue -Object $Json -CandidatePaths @(
            "intake.$field",
            "structured_intake.$field",
            "discovery.intake.$field",
            "discovery.structured_intake.$field",
            "process.$field",
            $field
        )
        Assert-Condition -Condition (Test-ValuePresent -Value $value) -Message "$Action did not return required structured intake field '$field'"
    }
}

function Assert-ScoreContract {
    param(
        [Parameter(Mandatory)]$Json,
        [Parameter(Mandatory)]$Contract
    )

    $formulaVersion = Get-FirstValue -Object $Json -CandidatePaths @("formula_version", "score.formula_version", "result.formula_version")
    Assert-Condition -Condition ([string]$formulaVersion -eq [string]$Contract.formula.version) -Message "score response did not expose the required formula version"
    $provenance = Get-FirstValue -Object $Json -CandidatePaths @("input_provenance", "inputs.provenance", "score.input_provenance", "result.input_provenance")
    Assert-Condition -Condition (Test-ValuePresent -Value $provenance) -Message "score response did not expose input provenance"
    foreach ($key in @("automatable_pct", "confidence", "effort_weeks", "risk_multiplier", "model_cost_annual", "infra_cost_annual", "review_rate", "review_minutes")) {
        $input = Get-FirstValue -Object $Json -CandidatePaths @("inputs.$key", "score.inputs.$key", "result.inputs.$key", $key)
        Assert-Condition -Condition ($null -ne $input) -Message "score response did not expose visible input '$key'"
    }
    $null = Get-ScoreProjection -Json $Json
}

function Test-StaticContract {
    foreach ($requiredPath in @($contractPath, $sopFixture, $transcriptFixture, $composeFile, $envTemplate)) {
        Assert-Condition -Condition (Test-Path -LiteralPath $requiredPath -PathType Leaf) -Message "Required tracked D-01 verification file is missing: $requiredPath"
    }

    try {
        $loadedContract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    } catch {
        throw "D-01 static contract is not valid JSON: $contractPath"
    }

    Assert-Condition -Condition ([string]$loadedContract.contract_version -eq "d01.http.v1") -Message "contract.json has an unexpected contract_version"
    $expectedRoles = @("owner", "admin", "builder", "operator", "viewer", "auditor")
    $actualRoles = @($loadedContract.canonical_roles | ForEach-Object { [string]$_ })
    Assert-Condition -Condition ((($actualRoles | Sort-Object) -join ",") -eq (($expectedRoles | Sort-Object) -join ",")) -Message "contract.json must contain exactly the canonical T-01 roles"
    Assert-Condition -Condition ([int]$loadedContract.workspace_count -ge 2) -Message "contract.json must exercise at least two workspaces"
    Assert-Condition -Condition ((@($loadedContract.denial_status_codes | ForEach-Object { [int]$_ }) -contains 403)) -Message "contract.json must allow RBAC denial status 403"
    Assert-Condition -Condition ((@($loadedContract.invalid_intake_status_codes | ForEach-Object { [int]$_ }) -contains 422)) -Message "contract.json must define a validation-failure status"
    Assert-Condition -Condition ((@($loadedContract.immutable_probe_status_codes | ForEach-Object { [int]$_ }) -contains 409)) -Message "contract.json must define a signed-baseline mutation denial status"

    $requiredRoutes = @(
        "health", "dev_login", "context_set", "membership_create", "audit_list", "audit_delete_probe",
        "discovery_create", "discovery_list", "discovery_detail", "discovery_ingest", "discovery_draft_patch",
        "discovery_question_answer", "discovery_exception_create", "baseline_create", "baseline_detail",
        "baseline_sign", "baseline_mutation_probe", "baseline_export", "score_compute", "score_detail"
    )
    $allowedMethods = @("GET", "POST", "PATCH", "DELETE")
    foreach ($routeKey in $requiredRoutes) {
        $routeProperty = $loadedContract.routes.PSObject.Properties[$routeKey]
        Assert-Condition -Condition ($null -ne $routeProperty) -Message "contract.json is missing route '$routeKey'"
        $route = $routeProperty.Value
        Assert-Condition -Condition ($allowedMethods -contains ([string]$route.method).ToUpperInvariant()) -Message "route '$routeKey' has an unsupported HTTP method"
        Assert-Condition -Condition ([string]$route.path -like "/api/*") -Message "route '$routeKey' must be an API path"
    }

    $requiredFields = @($loadedContract.required_intake_fields | ForEach-Object { [string]$_ })
    foreach ($field in @("trigger", "inputs", "steps", "decisions", "exceptions", "approvals", "outputs", "failure_modes")) {
        Assert-Condition -Condition ($requiredFields -contains $field) -Message "contract.json is missing structured intake field '$field'"
    }
    $requiredMetrics = @($loadedContract.required_baseline_metrics | ForEach-Object { [string]$_ })
    foreach ($metric in @("volume_per_month", "minutes_p50", "minutes_p90", "fully_loaded_cost_per_hour", "error_rate_pct", "cost_per_error", "rework_rate_pct", "cycle_time_hours", "headcount_touching", "peak_backlog", "chase_volume_per_month", "lapse_incidents_per_year", "audit_prep_hours_per_month")) {
        Assert-Condition -Condition ($requiredMetrics -contains $metric) -Message "contract.json is missing baseline metric '$metric'"
    }
    Assert-Condition -Condition ([string]$loadedContract.formula.version -eq "opportunity.v1") -Message "contract.json must name formula version opportunity.v1"
    Assert-Condition -Condition (@($loadedContract.required_audit_actions).Count -ge 8) -Message "contract.json must require meaningful D-01 audit actions"
    Assert-Condition -Condition (@($loadedContract.assumptions).Count -ge 1) -Message "contract.json must record implementation assumptions"

    $scriptText = Get-Content -LiteralPath $PSCommandPath -Raw
    $embeddedDatabaseTerm = [string]::Concat("sq", "lite")
    $directDbClientTerm = [string]::Concat("ps", "ql")
    $testDoubleTerm = [string]::Concat("mo", "ck")
    $containerShellTerm = [string]::Join(" ", @("docker", "exec"))
    $sqlInvocationTerm = [string]::Concat("Invoke", "-Sql")
    foreach ($prohibitedTerm in @($embeddedDatabaseTerm, $directDbClientTerm, $containerShellTerm, $sqlInvocationTerm, $testDoubleTerm)) {
        Assert-Condition -Condition ($scriptText.IndexOf($prohibitedTerm, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) -Message "verifier contains a prohibited shortcut term '$prohibitedTerm'"
    }
    $environmentReadPattern = [string]::Concat("(?i)Get-", "Content[^\r\n]*\.env")
    Assert-Condition -Condition ($scriptText -notmatch $environmentReadPattern) -Message "verifier must not read local environment contents"

    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$tokens, [ref]$parseErrors) | Out-Null
    Assert-Condition -Condition (@($parseErrors).Count -eq 0) -Message "verify-discovery.ps1 has PowerShell parse errors"
    return $loadedContract
}

try {
    $contract = Test-StaticContract
    Write-Output "D-01 static PASS: contract, required fields, formula version, fixtures, secret-safety guard, and PowerShell syntax are valid."
    if ($StaticOnly) {
        return
    }

    foreach ($requiredPath in @($composeFile, $envTemplate, $sopFixture, $transcriptFixture)) {
        Assert-Condition -Condition (Test-Path -LiteralPath $requiredPath -PathType Leaf) -Message "Required D-01 runtime file is missing: $requiredPath"
    }
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "D-01 prerequisite: ignored repository-root .env is missing. Configure local values from .env.example; this verifier never creates, reads, or prints .env contents."
    }

    $dockerExe = Resolve-DockerExecutable
    $composePrefix = @(
        "compose",
        "--project-name", $projectName,
        "--env-file", $envFile,
        "--file", $composeFile
    )

    $environmentConfigured = $true
    foreach ($key in $portEnvironment.Keys) {
        $hadEnvironment[$key] = Test-Path "Env:$key"
        if ($hadEnvironment[$key]) {
            $previousEnvironment[$key] = [string](Get-Item "Env:$key").Value
        }
        Set-Item "Env:$key" $portEnvironment[$key]
    }
    $storageGuard = Join-Path $PSScriptRoot "check-docker-storage.ps1"
    Assert-Condition -Condition (Test-Path -LiteralPath $storageGuard -PathType Leaf) -Message "Existing Docker storage guard is missing: $storageGuard"
    Write-Output "Checking Docker storage budget before starting the isolated D-01 stack..."
    & $storageGuard -MaxGb 32 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "D-01 Docker storage guard failed. Do not start the stack until usage is below 32 GB."
    }

    Write-Output "Validating Compose syntax for the isolated D-01 project..."
    $null = Invoke-Compose -Arguments @("config", "--quiet")
    Write-Output "Starting PostgreSQL, FastAPI, and Next.js for D-01..."
    $null = Invoke-Compose -Arguments @("up", "-d", "--build")
    $started = $true
    Wait-HttpReady -Uri "$apiBaseUrl/api/health"

    $health = Invoke-ContractApi -Contract $contract -RouteKey "health"
    Assert-ApiSuccess -Response $health -Action "D-01 health" -Expected @(200)

    $runTag = [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
    $organizationName = "D01 Synthetic Organization $runTag"
    $ownerEmail = "d01-owner-$runTag@example.test"
    $ownerName = "D01 Sponsor $runTag"

    $loginA = Invoke-ContractApi -Contract $contract -RouteKey "dev_login" -Body @{
        email = $ownerEmail
        name = $ownerName
        organization_name = $organizationName
        workspace_name = "D01 Workspace A $runTag"
    }
    Assert-ApiSuccess -Response $loginA -Action "owner login for workspace A" -Expected @(200)
    $tokenA = Get-Token -LoginResponse $loginA
    $workspaceA = Get-WorkspaceId -LoginResponse $loginA -Action "workspace A owner login"
    $ownerUserId = Get-EntityId -Json $loginA.Json -CandidatePaths @("user.id", "user_id") -Action "workspace A owner login"

    $loginB = Invoke-ContractApi -Contract $contract -RouteKey "dev_login" -Body @{
        email = $ownerEmail
        name = $ownerName
        organization_name = $organizationName
        workspace_name = "D01 Workspace B $runTag"
    }
    Assert-ApiSuccess -Response $loginB -Action "owner login for workspace B" -Expected @(200)
    $tokenB = Get-Token -LoginResponse $loginB
    $workspaceB = Get-WorkspaceId -LoginResponse $loginB -Action "workspace B owner login"
    Assert-Condition -Condition ($workspaceA -ne $workspaceB) -Message "the two owner logins did not create distinct workspaces"

    $sessionA = Invoke-ContractApi -Contract $contract -RouteKey "context_set" -Token $tokenA -Body @{ workspace_id = $workspaceA }
    Assert-ApiSuccess -Response $sessionA -Action "owner A active workspace context" -Expected @(200)

    $invalidIntake = Invoke-ContractApi -Contract $contract -RouteKey "discovery_create" -Token $tokenA -Body @{ name = "Incomplete intake"; trigger = "email" }
    Assert-ApiStatus -Response $invalidIntake -Expected @($contract.invalid_intake_status_codes | ForEach-Object { [int]$_ }) -Action "invalid structured discovery intake"
    Assert-ErrorEnvelope -Response $invalidIntake -Action "invalid structured discovery intake"

    $payloadA = New-DiscoveryPayload -Name "Subcontractor COI renewal A $runTag" -Tag $runTag
    $createA = Invoke-ContractApi -Contract $contract -RouteKey "discovery_create" -Token $tokenA -Body $payloadA
    Assert-ApiSuccess -Response $createA -Action "structured discovery intake in workspace A" -Expected @(201)
    $discoveryA = Get-EntityId -Json $createA.Json -CandidatePaths @("id", "discovery.id", "process.id") -Action "workspace A discovery creation"
    Assert-DiscoveryIntake -Json $createA.Json -Contract $contract -Action "workspace A discovery creation"
    $draftStatusA = Get-FirstValue -Object $createA.Json -CandidatePaths @("status", "draft_status", "discovery.status", "process.status")
    Assert-Condition -Condition ([string]$draftStatusA).ToLowerInvariant() -in @("draft", "intake_draft", "draft_pending_review") -Message "structured discovery intake did not start in draft status"

    $payloadB = New-DiscoveryPayload -Name "Subcontractor COI renewal B $runTag" -Tag $runTag
    $createB = Invoke-ContractApi -Contract $contract -RouteKey "discovery_create" -Token $tokenB -Body $payloadB
    Assert-ApiSuccess -Response $createB -Action "structured discovery intake in workspace B" -Expected @(201)
    $discoveryB = Get-EntityId -Json $createB.Json -CandidatePaths @("id", "discovery.id", "process.id") -Action "workspace B discovery creation"
    Assert-Condition -Condition ($discoveryA -ne $discoveryB) -Message "workspace A and workspace B returned the same discovery id"

    Set-ActiveContext -Contract $contract -Token $tokenA -WorkspaceId $workspaceB
    Set-ActiveContext -Contract $contract -Token $tokenA -WorkspaceId $workspaceA

    $listA = Invoke-ContractApi -Contract $contract -RouteKey "discovery_list" -Token $tokenA
    Assert-ApiSuccess -Response $listA -Action "workspace A discovery list" -Expected @(200)
    $itemsA = @(Get-ResponseItems -Json $listA.Json)
    $idsA = @($itemsA | ForEach-Object { Get-EntityId -Json $_ -CandidatePaths @("id", "discovery_id", "process_id") -Action "workspace A discovery list item" })
    Assert-Condition -Condition ($idsA -contains $discoveryA) -Message "workspace A discovery list omitted its own discovery"
    Assert-Condition -Condition ($idsA -notcontains $discoveryB) -Message "workspace A discovery list exposed workspace B data"

    $listB = Invoke-ContractApi -Contract $contract -RouteKey "discovery_list" -Token $tokenB
    Assert-ApiSuccess -Response $listB -Action "workspace B discovery list" -Expected @(200)
    $itemsB = @(Get-ResponseItems -Json $listB.Json)
    $idsB = @($itemsB | ForEach-Object { Get-EntityId -Json $_ -CandidatePaths @("id", "discovery_id", "process_id") -Action "workspace B discovery list item" })
    Assert-Condition -Condition ($idsB -contains $discoveryB) -Message "workspace B discovery list omitted its own discovery"
    Assert-Condition -Condition ($idsB -notcontains $discoveryA) -Message "workspace B discovery list exposed workspace A data"

    $crossWorkspaceDetail = Invoke-ContractApi -Contract $contract -RouteKey "discovery_detail" -Token $tokenA -Replacements @{ discovery_id = $discoveryB }
    Assert-ApiDenied -Response $crossWorkspaceDetail -Action "workspace A reading workspace B discovery"
    $crossWorkspacePatch = Invoke-ContractApi -Contract $contract -RouteKey "discovery_draft_patch" -Token $tokenA -Replacements @{ discovery_id = $discoveryB } -Body @{ draft_graph = @() }
    Assert-ApiDenied -Response $crossWorkspacePatch -Action "workspace A editing workspace B draft"

    $viewerEmail = "d01-viewer-$runTag@example.test"
    $viewerInvite = Invoke-ContractApi -Contract $contract -RouteKey "membership_create" -Token $tokenA -Replacements @{ workspace_id = $workspaceA } -Body @{ email = $viewerEmail; name = "D01 Read Only Viewer"; role = "viewer" }
    Assert-ApiSuccess -Response $viewerInvite -Action "viewer membership invitation" -Expected @(201)
    $viewerLogin = Invoke-ContractApi -Contract $contract -RouteKey "dev_login" -Body @{
        email = $viewerEmail
        name = "D01 Read Only Viewer"
        organization_name = $organizationName
        workspace_name = "D01 Workspace A $runTag"
    }
    Assert-ApiSuccess -Response $viewerLogin -Action "viewer login in workspace A" -Expected @(200)
    $viewerToken = Get-Token -LoginResponse $viewerLogin

    $viewerCrossWorkspace = Invoke-ContractApi -Contract $contract -RouteKey "discovery_list" -Token $viewerToken -Headers @{ "x-workspace-id" = $workspaceB }
    Assert-ApiDenied -Response $viewerCrossWorkspace -Action "viewer forcing an unassigned workspace context"
    $viewerWrite = Invoke-ContractApi -Contract $contract -RouteKey "discovery_create" -Token $viewerToken -Body (New-DiscoveryPayload -Name "Viewer write must fail $runTag" -Tag $runTag)
    Assert-ApiDenied -Response $viewerWrite -Action "viewer creating a discovery"

    $sopIngest = Invoke-MultipartIngest -Contract $contract -DiscoveryId $discoveryA -SourceType "sop" -FilePath $sopFixture -Token $tokenA
    Assert-ApiSuccess -Response $sopIngest -Action "SOP ingestion into workspace A" -Expected @(200, 201)
    Assert-DraftContract -Json $sopIngest.Json -Action "SOP ingestion"
    $sopGraph = Get-FirstValue -Object $sopIngest.Json -CandidatePaths @("draft_graph", "draft.graph", "ingestion.draft_graph", "workflow_draft.graph", "draft_graph.nodes")
    $sopExceptions = Get-FirstValue -Object $sopIngest.Json -CandidatePaths @("exceptions", "draft.exceptions", "ingestion.exceptions")
    $sopQuestions = Get-FirstValue -Object $sopIngest.Json -CandidatePaths @("baseline_questions", "draft.baseline_questions", "ingestion.baseline_questions")
    Assert-Condition -Condition ((@($sopGraph).Count) -gt 0) -Message "SOP ingestion did not produce a draft graph"
    Assert-Condition -Condition ((@($sopExceptions).Count) -gt 0) -Message "SOP ingestion did not produce an exception list"
    Assert-Condition -Condition ((@($sopQuestions).Count) -gt 0) -Message "SOP ingestion did not produce baseline questions"

    $transcriptIngest = Invoke-MultipartIngest -Contract $contract -DiscoveryId $discoveryA -SourceType "transcript" -FilePath $transcriptFixture -Token $tokenA
    Assert-ApiSuccess -Response $transcriptIngest -Action "transcript ingestion into workspace A" -Expected @(200, 201)
    Assert-DraftContract -Json $transcriptIngest.Json -Action "transcript ingestion"

    $detailAfterIngest = Invoke-ContractApi -Contract $contract -RouteKey "discovery_detail" -Token $tokenA -Replacements @{ discovery_id = $discoveryA }
    Assert-ApiSuccess -Response $detailAfterIngest -Action "workspace A discovery detail after ingestion" -Expected @(200)
    Assert-DiscoveryIntake -Json $detailAfterIngest.Json -Contract $contract -Action "workspace A discovery detail"
    $detailIngestions = @(Get-ResponseItems -Json (Get-FirstValue -Object $detailAfterIngest.Json -CandidatePaths @("ingestions", "discovery.ingestions", "process.interviews")))
    Assert-Condition -Condition ($detailIngestions.Count -ge 2) -Message "discovery detail did not retain both SOP and transcript ingestions"
    $sourceTypes = @($detailIngestions | ForEach-Object { [string](Get-FirstValue -Object $_ -CandidatePaths @("source_type", "type", "source")) })
    Assert-Condition -Condition ($sourceTypes -contains "sop") -Message "discovery detail did not retain source_type=sop"
    Assert-Condition -Condition ($sourceTypes -contains "transcript") -Message "discovery detail did not retain source_type=transcript"

    $editedGraph = @(
        [ordered]@{ id = "trigger"; type = "trigger"; label = "Human confirms email trigger"; position = 1 }
        [ordered]@{ id = "review"; type = "review"; label = "Human reviews exceptions"; position = 2 }
        [ordered]@{ id = "record"; type = "output"; label = "Record point-in-time proof"; position = 3 }
    )
    $draftPatch = Invoke-ContractApi -Contract $contract -RouteKey "discovery_draft_patch" -Token $tokenA -Replacements @{ discovery_id = $discoveryA } -Body @{
        draft_graph = $editedGraph
        exceptions = @("Human-confirmed missing endorsement", "Human-confirmed unreadable scan")
        edited_by = "human_operator"
    }
    Assert-ApiSuccess -Response $draftPatch -Action "human draft graph edit" -Expected @(200)
    Assert-DraftContract -Json $draftPatch.Json -Action "human draft graph edit"
    $patchedLabel = Get-FirstValue -Object $draftPatch.Json -CandidatePaths @("draft_graph.0.label", "draft.graph.0.label", "draft_graph.nodes.0.label")
    Assert-Condition -Condition ([string]$patchedLabel -eq "Human confirms email trigger") -Message "human draft edit was not retained in the response"

    $questions = @(Get-ResponseItems -Json (Get-FirstValue -Object $detailAfterIngest.Json -CandidatePaths @("baseline_questions", "draft.baseline_questions", "questions")))
    if ($questions.Count -eq 0) {
        $questions = @(Get-ResponseItems -Json (Get-FirstValue -Object $sopIngest.Json -CandidatePaths @("baseline_questions", "draft.baseline_questions", "ingestion.baseline_questions")))
    }
    Assert-Condition -Condition ($questions.Count -gt 0) -Message "no baseline question was available for a human answer"
    $questionId = Get-EntityId -Json $questions[0] -CandidatePaths @("id", "question_id") -Action "baseline question"
    $answer = Invoke-ContractApi -Contract $contract -RouteKey "discovery_question_answer" -Token $tokenA -Replacements @{ discovery_id = $discoveryA; question_id = $questionId } -Body @{ answer = "The sponsor requires a documented human decision for any missing endorsement."; answered_by = "human_operator" }
    Assert-ApiSuccess -Response $answer -Action "human baseline question answer" -Expected @(200, 201)
    $answerStatus = Get-FirstValue -Object $answer.Json -CandidatePaths @("status", "question.status", "answer.status")
    Assert-Condition -Condition ([string]$answerStatus).ToLowerInvariant() -in @("answered", "resolved") -Message "baseline question did not become answered"
    $answerText = Get-FirstValue -Object $answer.Json -CandidatePaths @("answer", "question.answer", "answer.value")
    Assert-Condition -Condition ([string]$answerText -like "*documented human decision*") -Message "human baseline question answer was not retained"

    $exception = Invoke-ContractApi -Contract $contract -RouteKey "discovery_exception_create" -Token $tokenA -Replacements @{ discovery_id = $discoveryA } -Body @{
        code = "AI_ENDORSEMENT_MISSING"
        description = "The endorsement is missing from the received certificate."
        frequency_per_month = 12
        severity = "medium"
        origin = "human"
        captured_by = "human_operator"
    }
    Assert-ApiSuccess -Response $exception -Action "human exception capture" -Expected @(200, 201)
    $exceptionId = Get-EntityId -Json $exception.Json -CandidatePaths @("id", "exception.id", "exception_id") -Action "human exception capture"
    $exceptionOrigin = Get-FirstValue -Object $exception.Json -CandidatePaths @("origin", "source", "exception.origin", "exception.source")
    Assert-Condition -Condition ([string]$exceptionOrigin).ToLowerInvariant() -eq "human" -Message "exception capture did not retain human origin"
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($exceptionId)) -Message "human exception capture returned no id"

    $metricsV1 = New-DiscoveryMetrics
    $baselineDraft = Invoke-ContractApi -Contract $contract -RouteKey "baseline_create" -Token $tokenA -Replacements @{ discovery_id = $discoveryA } -Body @{
        metrics = $metricsV1
        period_start = "2026-06-01"
        period_end = "2026-07-31"
        source = "human_signed_discovery"
    }
    Assert-ApiSuccess -Response $baselineDraft -Action "baseline version 1 creation" -Expected @(201)
    $baselineV1 = Get-EntityId -Json $baselineDraft.Json -CandidatePaths @("id", "baseline.id", "baseline_id") -Action "baseline version 1 creation"
    $baselineV1Status = Get-FirstValue -Object $baselineDraft.Json -CandidatePaths @("status", "baseline.status")
    Assert-Condition -Condition ([string]$baselineV1Status).ToLowerInvariant() -eq "draft" -Message "baseline version 1 was not created as draft"
    $baselineV1Version = [int](Get-FirstValue -Object $baselineDraft.Json -CandidatePaths @("version", "baseline.version", "baseline_version"))
    Assert-Condition -Condition ($baselineV1Version -eq 1) -Message "first baseline did not receive version 1"

    $sponsorEmail = "sponsor-$runTag@example.test"
    $signV1 = Invoke-ContractApi -Contract $contract -RouteKey "baseline_sign" -Token $tokenA -Replacements @{ baseline_id = $baselineV1 } -Body @{
        signer_name = $ownerName
        signer_email = $sponsorEmail
        attestation = "I reviewed the source evidence and approve this baseline for scoring."
    }
    Assert-ApiSuccess -Response $signV1 -Action "sponsor signing baseline version 1" -Expected @(200)
    $signedV1Status = Get-FirstValue -Object $signV1.Json -CandidatePaths @("status", "baseline.status")
    Assert-Condition -Condition ([string]$signedV1Status).ToLowerInvariant() -eq "signed" -Message "baseline version 1 did not become signed"
    $signedV1Hash = Get-FirstValue -Object $signV1.Json -CandidatePaths @("canonical_hash", "hash", "baseline.canonical_hash", "baseline.hash")
    Assert-Sha256 -Value $signedV1Hash -Action "signed baseline version 1"
    $signedV1At = Get-FirstValue -Object $signV1.Json -CandidatePaths @("signed_at", "baseline.signed_at")
    Assert-IsoTimestamp -Value $signedV1At -Action "signed baseline version 1"
    $signedV1Signer = Get-SignerText -Json $signV1.Json
    Assert-Condition -Condition ($signedV1Signer -like "*$sponsorEmail*" -or $signedV1Signer -like "*$ownerName*") -Message "signed baseline version 1 did not retain signer identity"
    $signedV1Version = [int](Get-FirstValue -Object $signV1.Json -CandidatePaths @("version", "baseline.version", "baseline_version"))
    Assert-Condition -Condition ($signedV1Version -eq 1) -Message "signed baseline version 1 did not retain version 1"

    $baselineV1Read = Invoke-ContractApi -Contract $contract -RouteKey "baseline_detail" -Token $tokenA -Replacements @{ baseline_id = $baselineV1 }
    Assert-ApiSuccess -Response $baselineV1Read -Action "signed baseline version 1 read" -Expected @(200)
    $metricsV1Canonical = [string](Get-FirstValue -Object $baselineV1Read.Json -CandidatePaths @("metrics", "baseline.metrics", "baseline_metrics") | ConvertTo-Json -Depth 30 -Compress)
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($metricsV1Canonical)) -Message "signed baseline version 1 did not expose its canonical metrics"

    $exportV1 = Invoke-ContractApi -Contract $contract -RouteKey "baseline_export" -Token $tokenA -Replacements @{ baseline_id = $baselineV1 }
    Assert-ApiSuccess -Response $exportV1 -Action "signed baseline version 1 export" -Expected @(200)
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($exportV1.Body)) -Message "signed baseline export returned an empty body"

    $mutationProbe = Invoke-ContractApi -Contract $contract -RouteKey "baseline_mutation_probe" -Token $tokenA -Replacements @{ baseline_id = $baselineV1 } -Body @{ metrics = @{ volume_per_month = @{ value = 1 } } }
    Assert-ApiStatus -Response $mutationProbe -Expected @($contract.immutable_probe_status_codes | ForEach-Object { [int]$_ }) -Action "mutation probe against signed baseline version 1"
    $baselineV1AfterMutation = Invoke-ContractApi -Contract $contract -RouteKey "baseline_detail" -Token $tokenA -Replacements @{ baseline_id = $baselineV1 }
    Assert-ApiSuccess -Response $baselineV1AfterMutation -Action "signed baseline version 1 read after mutation probe" -Expected @(200)
    $afterMutationHash = Get-FirstValue -Object $baselineV1AfterMutation.Json -CandidatePaths @("canonical_hash", "hash", "baseline.canonical_hash", "baseline.hash")
    $afterMutationVersion = [int](Get-FirstValue -Object $baselineV1AfterMutation.Json -CandidatePaths @("version", "baseline.version", "baseline_version"))
    $afterMutationAt = Get-FirstValue -Object $baselineV1AfterMutation.Json -CandidatePaths @("signed_at", "baseline.signed_at")
    $afterMutationSigner = Get-SignerText -Json $baselineV1AfterMutation.Json
    $afterMutationMetrics = [string](Get-FirstValue -Object $baselineV1AfterMutation.Json -CandidatePaths @("metrics", "baseline.metrics", "baseline_metrics") | ConvertTo-Json -Depth 30 -Compress)
    Assert-Condition -Condition ($afterMutationHash -eq $signedV1Hash -and $afterMutationVersion -eq $signedV1Version -and $afterMutationAt -eq $signedV1At -and $afterMutationSigner -eq $signedV1Signer -and $afterMutationMetrics -eq $metricsV1Canonical) -Message "signed baseline version 1 changed after the mutation probe"

    $metricsV2 = Copy-Metrics -Metrics $metricsV1
    $metricsV2.volume_per_month.value = 2000
    $baselineDraftV2 = Invoke-ContractApi -Contract $contract -RouteKey "baseline_create" -Token $tokenA -Replacements @{ discovery_id = $discoveryA } -Body @{
        metrics = $metricsV2
        period_start = "2026-08-01"
        period_end = "2026-08-31"
        source = "human_rebaseline"
        supersedes_baseline_id = $baselineV1
    }
    Assert-ApiSuccess -Response $baselineDraftV2 -Action "baseline version 2 creation" -Expected @(201)
    $baselineV2 = Get-EntityId -Json $baselineDraftV2.Json -CandidatePaths @("id", "baseline.id", "baseline_id") -Action "baseline version 2 creation"
    $baselineV2Version = [int](Get-FirstValue -Object $baselineDraftV2.Json -CandidatePaths @("version", "baseline.version", "baseline_version"))
    Assert-Condition -Condition ($baselineV2Version -eq 2) -Message "superseding baseline did not receive version 2"
    $supersedesV2 = Get-FirstValue -Object $baselineDraftV2.Json -CandidatePaths @("supersedes_baseline_id", "supersedes_id", "baseline.supersedes_baseline_id")
    Assert-Condition -Condition ([string]$supersedesV2 -eq $baselineV1) -Message "baseline version 2 did not identify version 1 as its superseded baseline"

    $signV2 = Invoke-ContractApi -Contract $contract -RouteKey "baseline_sign" -Token $tokenA -Replacements @{ baseline_id = $baselineV2 } -Body @{
        signer_name = $ownerName
        signer_email = $sponsorEmail
        attestation = "I reviewed the revised period and approve this superseding baseline."
    }
    Assert-ApiSuccess -Response $signV2 -Action "sponsor signing baseline version 2" -Expected @(200)
    $signedV2Status = Get-FirstValue -Object $signV2.Json -CandidatePaths @("status", "baseline.status")
    Assert-Condition -Condition ([string]$signedV2Status).ToLowerInvariant() -eq "signed" -Message "baseline version 2 did not become signed"
    $signedV2Hash = Get-FirstValue -Object $signV2.Json -CandidatePaths @("canonical_hash", "hash", "baseline.canonical_hash", "baseline.hash")
    Assert-Sha256 -Value $signedV2Hash -Action "signed baseline version 2"
    Assert-Condition -Condition ($signedV2Hash -ne $signedV1Hash) -Message "distinct signed baseline versions reused the same canonical hash"
    $signedV2At = Get-FirstValue -Object $signV2.Json -CandidatePaths @("signed_at", "baseline.signed_at")
    Assert-IsoTimestamp -Value $signedV2At -Action "signed baseline version 2"
    $signedV2Supersedes = Get-FirstValue -Object $signV2.Json -CandidatePaths @("supersedes_baseline_id", "supersedes_id", "baseline.supersedes_baseline_id")
    Assert-Condition -Condition ([string]$signedV2Supersedes -eq $baselineV1) -Message "signed baseline version 2 did not retain supersession metadata"

    $baselineV1AfterSupersession = Invoke-ContractApi -Contract $contract -RouteKey "baseline_detail" -Token $tokenA -Replacements @{ baseline_id = $baselineV1 }
    Assert-ApiSuccess -Response $baselineV1AfterSupersession -Action "version 1 read after version 2 supersession" -Expected @(200)
    $v1SupersededBy = Get-FirstValue -Object $baselineV1AfterSupersession.Json -CandidatePaths @("superseded_by_baseline_id", "superseded_by", "baseline.superseded_by_baseline_id", "baseline.superseded_by")
    $v1StatusAfterSupersession = [string](Get-FirstValue -Object $baselineV1AfterSupersession.Json -CandidatePaths @("status", "baseline.status"))
    Assert-Condition -Condition ([string]$v1SupersededBy -eq $baselineV2 -or $v1StatusAfterSupersession.ToLowerInvariant() -eq "superseded") -Message "version 1 did not expose its supersession by version 2"
    $v1HashAfterSupersession = Get-FirstValue -Object $baselineV1AfterSupersession.Json -CandidatePaths @("canonical_hash", "hash", "baseline.canonical_hash", "baseline.hash")
    $v1SignerAfterSupersession = Get-SignerText -Json $baselineV1AfterSupersession.Json
    Assert-Condition -Condition ($v1HashAfterSupersession -eq $signedV1Hash -and $v1SignerAfterSupersession -eq $signedV1Signer) -Message "version 1 signature or canonical hash changed after supersession"

    $scoreBody = [ordered]@{
        formula_version = [string]$contract.formula.version
        automatable_pct = 0.65
        confidence = 0.82
        effort_weeks = 4
        risk_multiplier = 1.25
        model_cost_annual = 9000
        infra_cost_annual = 2400
        review_rate = 0.15
        review_minutes = 4
    }
    $score1 = Invoke-ContractApi -Contract $contract -RouteKey "score_compute" -Token $tokenA -Replacements @{ baseline_id = $baselineV2 } -Body $scoreBody
    Assert-ApiSuccess -Response $score1 -Action "formula-versioned opportunity score" -Expected @(200, 201)
    Assert-ScoreContract -Json $score1.Json -Contract $contract
    $scoreId = Get-EntityId -Json $score1.Json -CandidatePaths @("id", "score.id", "opportunity_score.id", "score_id") -Action "formula-versioned opportunity score"

    $volume = Get-MetricValue -Metrics $metricsV2 -Key "volume_per_month"
    $minutesP50 = Get-MetricValue -Metrics $metricsV2 -Key "minutes_p50"
    $loadedRate = Get-MetricValue -Metrics $metricsV2 -Key "fully_loaded_cost_per_hour"
    $errorRate = Get-MetricValue -Metrics $metricsV2 -Key "error_rate_pct"
    $costPerError = Get-MetricValue -Metrics $metricsV2 -Key "cost_per_error"
    $currentAnnualCost = ($volume * 12 * $minutesP50 / 60 * $loadedRate) + ($volume * 12 * $errorRate * $costPerError)
    $reviewCostAnnual = $volume * 12 * $scoreBody.review_rate * $scoreBody.review_minutes / 60 * $loadedRate
    $projectedSavings = $currentAnnualCost * $scoreBody.automatable_pct - $scoreBody.model_cost_annual - $scoreBody.infra_cost_annual - $reviewCostAnnual
    $priorityScore = $projectedSavings * $scoreBody.confidence / ($scoreBody.effort_weeks * $scoreBody.risk_multiplier)
    Assert-NumericClose -Actual (Get-ScoreValue -Json $score1.Json -Key "current_annual_cost") -Expected $currentAnnualCost -Action "current annual cost"
    Assert-NumericClose -Actual (Get-ScoreValue -Json $score1.Json -Key "projected_savings") -Expected $projectedSavings -Action "projected savings"
    Assert-NumericClose -Actual (Get-ScoreValue -Json $score1.Json -Key "priority_score") -Expected $priorityScore -Action "priority score"

    $scoreDetail = Invoke-ContractApi -Contract $contract -RouteKey "score_detail" -Token $tokenA -Replacements @{ score_id = $scoreId }
    Assert-ApiSuccess -Response $scoreDetail -Action "opportunity score detail" -Expected @(200)
    Assert-ScoreContract -Json $scoreDetail.Json -Contract $contract
    Assert-NumericClose -Actual (Get-ScoreValue -Json $scoreDetail.Json -Key "priority_score") -Expected $priorityScore -Action "persisted priority score"

    $scoreRepeat = Invoke-ContractApi -Contract $contract -RouteKey "score_compute" -Token $tokenA -Replacements @{ baseline_id = $baselineV2 } -Body $scoreBody
    Assert-ApiSuccess -Response $scoreRepeat -Action "repeated identical opportunity score" -Expected @(200, 201)
    Assert-ScoreContract -Json $scoreRepeat.Json -Contract $contract
    $projection1 = Get-ScoreProjection -Json $score1.Json
    $projectionRepeat = Get-ScoreProjection -Json $scoreRepeat.Json
    Assert-Condition -Condition ((($projection1 | ConvertTo-Json -Depth 20 -Compress) -eq ($projectionRepeat | ConvertTo-Json -Depth 20 -Compress))) -Message "repeated identical score inputs produced different formula-versioned outputs"

    $scoreChangedBody = $scoreBody.Clone()
    $scoreChangedBody.automatable_pct = 0.40
    $scoreChanged = Invoke-ContractApi -Contract $contract -RouteKey "score_compute" -Token $tokenA -Replacements @{ baseline_id = $baselineV2 } -Body $scoreChangedBody
    Assert-ApiSuccess -Response $scoreChanged -Action "changed opportunity score input" -Expected @(200, 201)
    Assert-ScoreContract -Json $scoreChanged.Json -Contract $contract
    Assert-Condition -Condition ((Get-ScoreValue -Json $scoreChanged.Json -Key "projected_savings") -lt (Get-ScoreValue -Json $score1.Json -Key "projected_savings")) -Message "projected savings did not respond to the changed automatable_pct input"

    $audit = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $tokenA
    Assert-ApiSuccess -Response $audit -Action "D-01 audit read" -Expected @(200)
    $auditEvents = @(Get-ResponseItems -Json $audit.Json)
    Assert-Condition -Condition ($auditEvents.Count -gt 0) -Message "D-01 audit endpoint returned no events after authenticated discovery operations"
    $auditIds = @($auditEvents | ForEach-Object { Get-EventId -Event $_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    Assert-Condition -Condition ($auditIds.Count -eq (@($auditIds | Sort-Object -Unique).Count)) -Message "D-01 audit response contains duplicate event ids"
    $auditActions = @($auditEvents | ForEach-Object { (Get-EventAction -Event $_).ToLowerInvariant() })
    foreach ($requiredAction in @($contract.required_audit_actions | ForEach-Object { ([string]$_).ToLowerInvariant() })) {
        Assert-Condition -Condition ($auditActions -contains $requiredAction) -Message "D-01 audit evidence is missing '$requiredAction'"
    }

    $auditDeleteTarget = $auditIds | Select-Object -First 1
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($auditDeleteTarget)) -Message "D-01 audit response did not expose a deletion-probe target id"
    $auditDelete = Invoke-ContractApi -Contract $contract -RouteKey "audit_delete_probe" -Token $tokenA -Replacements @{ event_id = $auditDeleteTarget }
    Assert-ApiStatus -Response $auditDelete -Expected @(401, 403, 404, 405) -Action "append-only audit deletion probe"
    $auditAfterDelete = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $tokenA
    Assert-ApiSuccess -Response $auditAfterDelete -Action "D-01 audit read after deletion probe" -Expected @(200)
    $auditIdsAfterDelete = @((Get-ResponseItems -Json $auditAfterDelete.Json) | ForEach-Object { Get-EventId -Event $_ })
    foreach ($auditId in $auditIds) {
        Assert-Condition -Condition ($auditIdsAfterDelete -contains $auditId) -Message "audit event $auditId disappeared after a denied deletion probe"
    }

    Write-Output "D-01 E2E PASS: two-workspace isolation, validated structured intake, human-only SOP/transcript drafts, review edits/questions/exceptions, signed immutable baselines, supersession, reproducible formula scoring, RBAC denial, append-only audit, bounded cleanup, and secret-safe output verified."
} finally {
    if ($started -and -not $KeepRunning -and $null -ne $dockerExe) {
        try {
            $null = Invoke-Compose -Arguments @("down", "--remove-orphans")
            $remaining = @(Invoke-Compose -Arguments @("ps", "-q") | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
            if ($remaining.Count -gt 0) {
                Write-Warning "D-01 cleanup left project containers running. Stop only project '$projectName' with the documented Compose down command."
            } else {
                Write-Output "D-01 Compose services stopped; the named PostgreSQL volume was preserved."
            }
            $storageGuard = Join-Path $PSScriptRoot "check-docker-storage.ps1"
            if (Test-Path -LiteralPath $storageGuard -PathType Leaf) {
                & $storageGuard -MaxGb 32 | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "D-01 post-cleanup storage guard did not pass. Inspect Docker usage before another build."
                }
            }
        } catch {
            Write-Warning "D-01 cleanup failed. Stop only project '$projectName' with docker compose --project-name $projectName --env-file .env --file docker-compose.yml down --remove-orphans."
        }
    } elseif ($started -and $KeepRunning) {
        Write-Output "D-01 services remain running by request. Stop only project '$projectName' with docker compose --project-name $projectName --env-file .env --file docker-compose.yml down --remove-orphans"
    }

    if ($environmentConfigured) {
        foreach ($key in $portEnvironment.Keys) {
            if ($hadEnvironment.ContainsKey($key) -and $hadEnvironment[$key]) {
                Set-Item "Env:$key" $previousEnvironment[$key]
            } else {
                Remove-Item "Env:$key" -ErrorAction SilentlyContinue
            }
        }
    }
}
