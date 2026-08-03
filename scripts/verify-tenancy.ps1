[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$contractPath = Join-Path $repoRoot "tests\tenancy\contract.json"
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$envTemplate = Join-Path $repoRoot ".env.example"
$fixture = Join-Path $repoRoot "tests\fixtures\coi-failing.txt"
$projectName = "ai-ops-platform-t01"
$apiBaseUrl = "http://localhost:8000"
$started = $false
$tempFixture = $null
$contract = $null

function Assert-Condition {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Message
    )

    if (-not $Condition) {
        throw "T-01 assertion failed: $Message Repair: inspect the first failing API response and the corresponding service logs."
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
        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return $null
        }
        $current = $property.Value
    }
    return $current
}

function Get-EntityId {
    param(
        [AllowNull()][object]$Json,
        [Parameter(Mandatory)][string[]]$CandidatePaths,
        [Parameter(Mandatory)][string]$Action
    )

    foreach ($candidatePath in $CandidatePaths) {
        $candidate = Get-JsonValue -Object $Json -Path $candidatePath
        if ($null -ne $candidate -and -not [string]::IsNullOrWhiteSpace([string]$candidate)) {
            return [string]$candidate
        }
    }
    throw "T-01 contract gap: $Action succeeded but did not return an id. Expected one of: $($CandidatePaths -join ', ')."
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

function Get-EventType {
    param([AllowNull()][object]$Event)

    foreach ($propertyName in @("event_type", "action", "type", "event")) {
        $property = $Event.PSObject.Properties[$propertyName]
        if ($null -ne $property -and $null -ne $property.Value) {
            return [string]$property.Value
        }
    }
    return ""
}

function Get-EventId {
    param([AllowNull()][object]$Event)

    foreach ($propertyName in @("id", "event_id", "audit_id")) {
        $property = $Event.PSObject.Properties[$propertyName]
        if ($null -ne $property -and $null -ne $property.Value) {
            return [string]$property.Value
        }
    }
    return ""
}

function Get-ContractRoute {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$RouteKey,
        [hashtable]$Replacements = @{}
    )

    $routeProperty = $Contract.routes.PSObject.Properties[$RouteKey]
    if ($null -eq $routeProperty) {
        throw "T-01 contract is missing route '$RouteKey'."
    }
    $route = $routeProperty.Value
    $path = [string]$route.path
    foreach ($replacementKey in $Replacements.Keys) {
        $path = $path.Replace("{$replacementKey}", [string]$Replacements[$replacementKey])
    }
    if ($path -match '\{[^}]+\}') {
        throw "T-01 route '$RouteKey' still has an unresolved path parameter: $path"
    }
    return [pscustomobject]@{
        Method = [string]$route.method
        Path = $path
    }
}

function Test-StaticContract {
    if (-not (Test-Path -LiteralPath $contractPath)) {
        throw "T-01 static prerequisite missing: $contractPath"
    }

    try {
        $loadedContract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
    } catch {
        throw "T-01 static contract is not valid JSON: $contractPath"
    }

    $expectedRoles = @("owner", "admin", "builder", "operator", "viewer", "auditor")
    $actualRoles = @($loadedContract.canonical_roles | ForEach-Object { [string]$_ })
    $actualRoleSignature = ($actualRoles | Sort-Object) -join ","
    $expectedRoleSignature = ($expectedRoles | Sort-Object) -join ","
    Assert-Condition -Condition ($actualRoleSignature -eq $expectedRoleSignature) -Message "contract.json must contain exactly the canonical role set owner, admin, builder, operator, viewer, auditor"
    Assert-Condition -Condition ([int]$loadedContract.tenant_count -ge 2) -Message "contract.json must exercise at least two tenants"
    Assert-Condition -Condition ([int]$loadedContract.workspaces_per_tenant -ge 2) -Message "contract.json must exercise at least two workspaces per tenant"

    $requiredRoutes = @(
        "register", "login", "me", "session_revoke", "organization_create",
        "workspace_create", "workspace_list", "membership_create", "membership_disable",
        "context_set", "audit_list", "audit_delete_probe", "vendors", "vendor_create",
        "vendor_detail", "documents_upload", "document_verify", "reviews", "review_update",
        "vendor_status", "vendor_ledger"
    )
    foreach ($routeKey in $requiredRoutes) {
        $routeProperty = $loadedContract.routes.PSObject.Properties[$routeKey]
        Assert-Condition -Condition ($null -ne $routeProperty) -Message "contract.json is missing route '$routeKey'"
        Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$routeProperty.Value.method)) -Message "route '$routeKey' is missing an HTTP method"
        Assert-Condition -Condition ([string]$routeProperty.Value.path -like "/api/*") -Message "route '$routeKey' must be an API path"
    }

    $denialCodes = @($loadedContract.denial_status_codes | ForEach-Object { [int]$_ })
    Assert-Condition -Condition (($denialCodes -contains 401) -and ($denialCodes -contains 403) -and ($denialCodes -contains 404)) -Message "contract.json must allow 401, 403, and 404 denial responses"
    $deleteCodes = @($loadedContract.audit_delete_status_codes | ForEach-Object { [int]$_ })
    Assert-Condition -Condition (($deleteCodes -contains 401) -and ($deleteCodes -contains 403) -and ($deleteCodes -contains 404) -and ($deleteCodes -contains 405)) -Message "contract.json must define non-success responses for audit deletion"

    $requiredAuditEvents = @("login", "workspace_context_changed", "access_denied", "vendor_created", "document_uploaded", "document_verified", "membership_disabled", "session_revoked", "sensitive_read")
    $actualAuditEvents = @($loadedContract.required_audit_events | ForEach-Object { [string]$_ })
    foreach ($eventName in $requiredAuditEvents) {
        Assert-Condition -Condition ($actualAuditEvents -contains $eventName) -Message "contract.json is missing required audit event '$eventName'"
    }
    Assert-Condition -Condition (@($loadedContract.assumptions).Count -ge 1) -Message "contract.json must record implementation assumptions"

    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$tokens, [ref]$parseErrors) | Out-Null
    Assert-Condition -Condition (@($parseErrors).Count -eq 0) -Message "verify-tenancy.ps1 has PowerShell parse errors"

    return $loadedContract
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

    throw "T-01 prerequisite: Docker executable was not found. Start Docker Desktop or refresh PATH, then rerun scripts\verify-tenancy.ps1."
}

function Invoke-Docker {
    param([Parameter(Mandatory)][string]$DockerPath, [Parameter(Mandatory)][string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $DockerPath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker command failed: $DockerPath $($Arguments -join ' '). Docker output is withheld to prevent accidental credential disclosure. Repair: inspect the named Compose project's service logs and rerun after fixing the first failing service."
    }
    return $output
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory)][string]$DockerPath,
        [Parameter(Mandatory)][string[]]$ComposePrefix,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    return Invoke-Docker -DockerPath $DockerPath -Arguments ($ComposePrefix + $Arguments)
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
    param([Parameter(Mandatory)][string]$Uri, [int]$Attempts = 60)

    $lastError = "no response"
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                Write-Output "T-01 service ready: GET $Uri"
                return
            }
            $lastError = "HTTP $($response.StatusCode)"
        } catch {
            $lastError = Get-HttpErrorBody -Exception $_.Exception
        }
        Start-Sleep -Seconds 2
    }
    throw "T-01 service readiness failed for GET $Uri after $Attempts attempts. Last response was not printed because it may contain implementation details. Repair: inspect 'docker compose logs backend postgres' and fix the first failing service."
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
            $json = $Body | ConvertTo-Json -Depth 20 -Compress
            $response = Invoke-WebRequest -Uri $uri -Method $Method -Headers $requestHeaders -ContentType "application/json" -Body $json -UseBasicParsing -TimeoutSec 20
        }
        $status = [int]$response.StatusCode
        $responseBody = [string]$response.Content
    } catch {
        $webResponse = $_.Exception.Response
        if ($null -eq $webResponse) {
            throw "T-01 HTTP transport failure for $Method ${Path}: $($_.Exception.Message)"
        }
        $status = [int]$webResponse.StatusCode
        $responseBody = Get-HttpErrorBody -Exception $_.Exception
    }

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
    return Invoke-Api -Method $route.Method -Path $route.Path -Body $Body -Token $Token -Headers $Headers
}

function Assert-ApiStatus {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][int[]]$Expected,
        [Parameter(Mandatory)][string]$Action
    )

    if ($Expected -notcontains [int]$Response.Status) {
        throw "T-01 contract failure: $Action returned HTTP $($Response.Status); expected $($Expected -join ', '). The response body is intentionally withheld. Contract assumptions are recorded in tests\tenancy\contract.json."
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

    Assert-ApiStatus -Response $Response -Expected $Expected -Action "$Action (scope denial)"
}

function Invoke-MultipartUpload {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$VendorId,
        [Parameter(Mandatory)][string]$FilePath,
        [AllowNull()][string]$Token = $null
    )

    Add-Type -AssemblyName System.Net.Http
    $route = Get-ContractRoute -Contract $Contract -RouteKey "documents_upload" -Replacements @{ vendor_id = $VendorId }
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        if (-not [string]::IsNullOrWhiteSpace($Token)) {
            $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
        }
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/plain")
        $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
        $form.Add([System.Net.Http.StringContent]::new("COI"), "doc_type")
        $response = $client.PostAsync("$apiBaseUrl$($route.Path)", $form).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
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
    Assert-ApiSuccess -Response $context -Action "POST /api/auth/context to workspace $WorkspaceId" -Expected @(200)
    $returnedWorkspaceId = Get-JsonValue -Object $context.Json -Path "active_workspace_id"
    if ($null -eq $returnedWorkspaceId) {
        $returnedWorkspaceId = Get-JsonValue -Object $context.Json -Path "workspace.id"
    }
    if ($null -ne $returnedWorkspaceId) {
        Assert-Condition -Condition ([string]$returnedWorkspaceId -eq [string]$WorkspaceId) -Message "active workspace context response did not match the requested workspace"
    }
}

try {
    $contract = Test-StaticContract
    Write-Output "T-01 static PASS: contract roles, route inventory, audit requirements, and PowerShell syntax are valid."
    if ($StaticOnly) {
        return
    }

    foreach ($requiredPath in @($composeFile, $envTemplate, $fixture)) {
        Assert-Condition -Condition (Test-Path -LiteralPath $requiredPath) -Message "Required tracked verification file is missing: $requiredPath"
    }
    if (-not (Test-Path -LiteralPath $envFile)) {
        throw "T-01 prerequisite: ignored repository-root .env is missing. Copy .env.example to .env in the coordinator checkout and fill local values; this verifier never creates, reads, or prints .env contents."
    }

    $dockerExe = Resolve-DockerExecutable
    $composePrefix = @(
        "compose",
        "--project-name", $projectName,
        "--env-file", $envFile,
        "--file", $composeFile
    )

    $storageGuard = Join-Path $PSScriptRoot "check-docker-storage.ps1"
    Assert-Condition -Condition (Test-Path -LiteralPath $storageGuard) -Message "Existing Docker storage guard is missing: $storageGuard"
    Write-Output "Checking Docker storage budget before starting the T-01 stack..."
    & $storageGuard -MaxGb 32
    $storageExitCode = $LASTEXITCODE
    if ($storageExitCode -ne 0) {
        throw "T-01 Docker storage guard failed. Do not start the stack until usage is below 32 GB."
    }

    Write-Output "Validating Compose syntax for the isolated T-01 project..."
    $null = Invoke-Compose -DockerPath $dockerExe -ComposePrefix $composePrefix -Arguments @("config", "--quiet")
    Write-Output "Starting PostgreSQL, backend, and frontend for T-01..."
    $null = Invoke-Compose -DockerPath $dockerExe -ComposePrefix $composePrefix -Arguments @("up", "-d", "--build")
    $started = $true
    Wait-HttpReady -Uri "$apiBaseUrl/api/health"

    $runTag = [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
    $password = "T01-only-$runTag"
    $roles = @("owner", "admin", "builder", "operator", "viewer", "auditor")
    $tenantKeys = @("a", "b")
    $tenantData = @{}

    foreach ($tenantKey in $tenantKeys) {
        $tenantData[$tenantKey] = [ordered]@{
            Users = @{}
            OrganizationId = $null
            Workspaces = @()
        }
        foreach ($role in $roles) {
            $email = "t01-$runTag-$tenantKey-$role@example.test"
            $register = Invoke-ContractApi -Contract $contract -RouteKey "register" -Body @{
                email = $email
                password = $password
                display_name = "T01 $tenantKey $role"
            }
            Assert-ApiSuccess -Response $register -Action "POST /api/auth/register for tenant $tenantKey role $role" -Expected @(200, 201)
            $userId = Get-EntityId -Json $register.Json -CandidatePaths @("user.id", "id") -Action "POST /api/auth/register for tenant $tenantKey role $role"
            $tenantData[$tenantKey].Users[$role] = [pscustomobject]@{
                Email = $email
                UserId = $userId
                Token = $null
                SessionId = $null
                Memberships = @{}
            }
        }

        $owner = $tenantData[$tenantKey].Users["owner"]
        $ownerLogin = Invoke-ContractApi -Contract $contract -RouteKey "login" -Body @{ email = $owner.Email; password = $password }
        Assert-ApiSuccess -Response $ownerLogin -Action "POST /api/auth/login for tenant $tenantKey owner" -Expected @(200)
        $owner.Token = Get-EntityId -Json $ownerLogin.Json -CandidatePaths @("access_token", "token", "session.access_token", "session.token") -Action "POST /api/auth/login for tenant $tenantKey owner"
        $owner.SessionId = Get-EntityId -Json $ownerLogin.Json -CandidatePaths @("session_id", "session.id") -Action "POST /api/auth/login for tenant $tenantKey owner"

        $organization = Invoke-ContractApi -Contract $contract -RouteKey "organization_create" -Token $owner.Token -Body @{
            name = "T01 Tenant $tenantKey $runTag"
            slug = "t01-$runTag-$tenantKey"
        }
        Assert-ApiSuccess -Response $organization -Action "POST /api/organizations for tenant $tenantKey" -Expected @(200, 201)
        $tenantData[$tenantKey].OrganizationId = Get-EntityId -Json $organization.Json -CandidatePaths @("organization.id", "id") -Action "POST /api/organizations for tenant $tenantKey"

        foreach ($workspaceNumber in 1..2) {
            $workspace = Invoke-ContractApi -Contract $contract -RouteKey "workspace_create" -Token $owner.Token -Body @{
                organization_id = $tenantData[$tenantKey].OrganizationId
                name = "T01 $tenantKey workspace $workspaceNumber $runTag"
                delivery_mode = "managed"
                handoff_mode = "human_review"
            }
            Assert-ApiSuccess -Response $workspace -Action "POST /api/workspaces for tenant $tenantKey workspace $workspaceNumber" -Expected @(200, 201)
            $workspaceId = Get-EntityId -Json $workspace.Json -CandidatePaths @("workspace.id", "id") -Action "POST /api/workspaces for tenant $tenantKey workspace $workspaceNumber"
            $tenantData[$tenantKey].Workspaces += [pscustomobject]@{
                Number = $workspaceNumber
                Id = $workspaceId
                Name = "T01 $tenantKey workspace $workspaceNumber $runTag"
            }
        }

        $workspaceOne = $tenantData[$tenantKey].Workspaces[0]
        $workspaceTwo = $tenantData[$tenantKey].Workspaces[1]
        foreach ($role in $roles | Where-Object { $_ -ne "owner" }) {
            $principal = $tenantData[$tenantKey].Users[$role]
            $membership = Invoke-ContractApi -Contract $contract -RouteKey "membership_create" -Token $owner.Token -Replacements @{ workspace_id = $workspaceOne.Id } -Body @{
                email = $principal.Email
                role = $role
            }
            Assert-ApiSuccess -Response $membership -Action "POST /api/workspaces/{workspace_id}/memberships for tenant $tenantKey role $role" -Expected @(200, 201)
            $principal.Memberships[([string]$workspaceOne.Number)] = Get-EntityId -Json $membership.Json -CandidatePaths @("membership.id", "id") -Action "membership creation for tenant $tenantKey role $role"
        }

        $operator = $tenantData[$tenantKey].Users["operator"]
        $operatorSecondMembership = Invoke-ContractApi -Contract $contract -RouteKey "membership_create" -Token $owner.Token -Replacements @{ workspace_id = $workspaceTwo.Id } -Body @{
            email = $operator.Email
            role = "operator"
        }
        Assert-ApiSuccess -Response $operatorSecondMembership -Action "second workspace membership for tenant $tenantKey operator" -Expected @(200, 201)
        $operator.Memberships[([string]$workspaceTwo.Number)] = Get-EntityId -Json $operatorSecondMembership.Json -CandidatePaths @("membership.id", "id") -Action "second workspace membership for tenant $tenantKey operator"
    }

    foreach ($tenantKey in $tenantKeys) {
        foreach ($role in $roles) {
            $principal = $tenantData[$tenantKey].Users[$role]
            $login = Invoke-ContractApi -Contract $contract -RouteKey "login" -Body @{ email = $principal.Email; password = $password }
            Assert-ApiSuccess -Response $login -Action "POST /api/auth/login for tenant $tenantKey role $role" -Expected @(200)
            $principal.Token = Get-EntityId -Json $login.Json -CandidatePaths @("access_token", "token", "session.access_token", "session.token") -Action "POST /api/auth/login for tenant $tenantKey role $role"
            $principal.SessionId = Get-EntityId -Json $login.Json -CandidatePaths @("session_id", "session.id") -Action "POST /api/auth/login for tenant $tenantKey role $role"

            $context = Invoke-ContractApi -Contract $contract -RouteKey "context_set" -Token $principal.Token -Body @{ workspace_id = $tenantData[$tenantKey].Workspaces[0].Id }
            Assert-ApiSuccess -Response $context -Action "POST /api/auth/context for tenant $tenantKey role $role" -Expected @(200)
        }
    }

    $tenantA = $tenantData["a"]
    $tenantB = $tenantData["b"]
    $workspaceA1 = $tenantA.Workspaces[0]
    $workspaceA2 = $tenantA.Workspaces[1]
    $workspaceB1 = $tenantB.Workspaces[0]
    $ownerA = $tenantA.Users["owner"]
    $adminA = $tenantA.Users["admin"]
    $builderA = $tenantA.Users["builder"]
    $operatorA = $tenantA.Users["operator"]
    $viewerA = $tenantA.Users["viewer"]
    $auditorA = $tenantA.Users["auditor"]
    $operatorB = $tenantB.Users["operator"]

    $adminProbeWorkspace = Invoke-ContractApi -Contract $contract -RouteKey "workspace_create" -Token $adminA.Token -Body @{
        organization_id = $tenantA.OrganizationId
        name = "T01 admin workspace probe $runTag"
        delivery_mode = "managed"
        handoff_mode = "human_review"
    }
    Assert-ApiSuccess -Response $adminProbeWorkspace -Action "admin workspace-management capability" -Expected @(200, 201)

    $adminProbeMembership = Invoke-ContractApi -Contract $contract -RouteKey "membership_create" -Token $adminA.Token -Replacements @{ workspace_id = $workspaceA2.Id } -Body @{
        email = $builderA.Email
        role = "builder"
    }
    Assert-ApiSuccess -Response $adminProbeMembership -Action "admin membership-management capability" -Expected @(200, 201)

    foreach ($role in @("builder", "operator", "viewer", "auditor")) {
        $principal = $tenantA.Users[$role]
        $workspaceAttempt = Invoke-ContractApi -Contract $contract -RouteKey "workspace_create" -Token $principal.Token -Body @{
            organization_id = $tenantA.OrganizationId
            name = "T01 forbidden workspace $role $runTag"
            delivery_mode = "managed"
            handoff_mode = "human_review"
        }
        Assert-ApiDenied -Response $workspaceAttempt -Action "$role workspace-management attempt"
    }

    foreach ($role in $roles) {
        $principal = $tenantA.Users[$role]
        $vendors = Invoke-ContractApi -Contract $contract -RouteKey "vendors" -Token $principal.Token
        Assert-ApiSuccess -Response $vendors -Action "$role vendor read in active workspace" -Expected @(200)
    }

    foreach ($role in @("builder", "viewer", "auditor")) {
        $principal = $tenantA.Users[$role]
        $vendorWrite = Invoke-ContractApi -Contract $contract -RouteKey "vendor_create" -Token $principal.Token -Body @{ legal_name = "T01 forbidden vendor $role $runTag" }
        Assert-ApiDenied -Response $vendorWrite -Action "$role vendor-write attempt"
    }

    foreach ($role in @("owner", "admin")) {
        $principal = $tenantA.Users[$role]
        $vendorWrite = Invoke-ContractApi -Contract $contract -RouteKey "vendor_create" -Token $principal.Token -Body @{ legal_name = "T01 allowed vendor $role $runTag" }
        Assert-ApiSuccess -Response $vendorWrite -Action "$role vendor-write capability" -Expected @(200, 201)
    }

    $operatorVendor = Invoke-ContractApi -Contract $contract -RouteKey "vendor_create" -Token $operatorA.Token -Body @{ legal_name = "T01 operator vendor $runTag" }
    Assert-ApiSuccess -Response $operatorVendor -Action "operator vendor-write capability" -Expected @(200, 201)
    $vendorId = Get-EntityId -Json $operatorVendor.Json -CandidatePaths @("vendor.id", "id") -Action "operator vendor creation"

    $fixtureText = [System.IO.File]::ReadAllText($fixture)
    $fixtureText = $fixtureText.Replace("{{VENDOR_NAME}}", "T01 operator vendor $runTag")
    $tempFixture = Join-Path ([System.IO.Path]::GetTempPath()) "ai-ops-t01-coi-$runTag.txt"
    [System.IO.File]::WriteAllText($tempFixture, $fixtureText, [System.Text.UTF8Encoding]::new($false))

    $upload = Invoke-MultipartUpload -Contract $contract -VendorId $vendorId -FilePath $tempFixture -Token $operatorA.Token
    Assert-ApiSuccess -Response $upload -Action "operator F01 document upload" -Expected @(200, 201)
    $documentId = Get-EntityId -Json $upload.Json -CandidatePaths @("document.id", "id") -Action "operator F01 document upload"

    $verification = Invoke-ContractApi -Contract $contract -RouteKey "document_verify" -Token $operatorA.Token -Replacements @{ document_id = $documentId }
    Assert-ApiSuccess -Response $verification -Action "operator F01 document verification" -Expected @(200, 201)
    $initialStatus = [string](Get-JsonValue -Object $verification.Json -Path "status.status")
    Assert-Condition -Condition ($initialStatus -eq "needs_review") -Message "F01 verification should produce needs_review for the failing fixture"

    $reviewsResponse = Invoke-ContractApi -Contract $contract -RouteKey "reviews" -Token $operatorA.Token
    Assert-ApiSuccess -Response $reviewsResponse -Action "operator F01 review list" -Expected @(200)
    $openReviews = @(Get-ResponseItems -Json $reviewsResponse.Json | Where-Object { $_.vendor_id -eq $vendorId -and $_.status -eq "open" })
    Assert-Condition -Condition ($openReviews.Count -ge 1) -Message "F01 verification did not create an open review task"
    $holderReview = $openReviews | Where-Object { $_.correction_field -eq "certificate_holder" } | Select-Object -First 1
    Assert-Condition -Condition ($null -ne $holderReview) -Message "F01 verification did not create the certificate_holder review task"
    $reviewId = Get-EntityId -Json $holderReview -CandidatePaths @("id", "review_id") -Action "F01 open certificate_holder review"

    foreach ($role in @("builder", "viewer", "auditor")) {
        $principal = $tenantA.Users[$role]
        $reviewAttempt = Invoke-ContractApi -Contract $contract -RouteKey "review_update" -Token $principal.Token -Replacements @{ review_id = $reviewId } -Body @{ field = "certificate_holder"; value = "T01 unauthorized correction" }
        Assert-ApiDenied -Response $reviewAttempt -Action "$role review-write attempt"
    }

    $correction = Invoke-ContractApi -Contract $contract -RouteKey "review_update" -Token $operatorA.Token -Replacements @{ review_id = $reviewId } -Body @{ field = "certificate_holder"; value = "Northwind Construction LLC" }
    Assert-ApiSuccess -Response $correction -Action "operator F01 review correction" -Expected @(200)
    $correctedStatus = [string](Get-JsonValue -Object $correction.Json -Path "status.status")
    Assert-Condition -Condition ($correctedStatus -eq "compliant") -Message "F01 review correction should produce compliant status"

    $statusResponse = Invoke-ContractApi -Contract $contract -RouteKey "vendor_status" -Token $operatorA.Token -Replacements @{ vendor_id = $vendorId }
    Assert-ApiSuccess -Response $statusResponse -Action "operator F01 status history" -Expected @(200)
    $history = @(Get-ResponseItems -Json (Get-JsonValue -Object $statusResponse.Json -Path "history"))
    Assert-Condition -Condition ($history.Count -ge 2) -Message "F01 status endpoint returned fewer than two point-in-time snapshots"
    Assert-Condition -Condition ((Get-EntityId -Json $history[0] -CandidatePaths @("id") -Action "first F01 status snapshot") -ne (Get-EntityId -Json $history[1] -CandidatePaths @("id") -Action "second F01 status snapshot")) -Message "F01 status history is not append-only"

    $ledgerResponse = Invoke-ContractApi -Contract $contract -RouteKey "vendor_ledger" -Token $operatorA.Token -Replacements @{ vendor_id = $vendorId }
    Assert-ApiSuccess -Response $ledgerResponse -Action "operator F01 ledger" -Expected @(200)
    $ledgerEvents = @(Get-ResponseItems -Json $ledgerResponse.Json)
    $ledgerTypes = @($ledgerEvents | ForEach-Object { Get-EventType -Event $_ })
    Assert-Condition -Condition ($ledgerTypes -contains "document_uploaded") -Message "F01 ledger is missing document_uploaded"
    Assert-Condition -Condition (($ledgerTypes | Where-Object { $_ -eq "verification_completed" }).Count -ge 2) -Message "F01 ledger is missing both verification_completed events"
    Assert-Condition -Condition ($ledgerTypes -contains "review_correction_applied") -Message "F01 ledger is missing review_correction_applied"

    foreach ($role in @("owner", "admin", "builder", "viewer", "auditor")) {
        $principal = $tenantA.Users[$role]
        $detail = Invoke-ContractApi -Contract $contract -RouteKey "vendor_detail" -Token $principal.Token -Replacements @{ vendor_id = $vendorId }
        Assert-ApiSuccess -Response $detail -Action "$role vendor read capability" -Expected @(200)
    }

    Set-ActiveContext -Contract $contract -Token $operatorA.Token -WorkspaceId $workspaceA2.Id
    $crossWorkspaceDetail = Invoke-ContractApi -Contract $contract -RouteKey "vendor_detail" -Token $operatorA.Token -Replacements @{ vendor_id = $vendorId }
    Assert-ApiDenied -Response $crossWorkspaceDetail -Action "same-tenant cross-workspace vendor read"
    $crossWorkspaceUpload = Invoke-MultipartUpload -Contract $contract -VendorId $vendorId -FilePath $tempFixture -Token $operatorA.Token
    Assert-ApiDenied -Response $crossWorkspaceUpload -Action "same-tenant cross-workspace document write"

    Set-ActiveContext -Contract $contract -Token $operatorB.Token -WorkspaceId $workspaceB1.Id
    $crossTenantDetail = Invoke-ContractApi -Contract $contract -RouteKey "vendor_detail" -Token $operatorB.Token -Replacements @{ vendor_id = $vendorId }
    Assert-ApiDenied -Response $crossTenantDetail -Action "cross-tenant vendor read"
    $crossTenantUpload = Invoke-MultipartUpload -Contract $contract -VendorId $vendorId -FilePath $tempFixture -Token $operatorB.Token
    Assert-ApiDenied -Response $crossTenantUpload -Action "cross-tenant document write"

    Set-ActiveContext -Contract $contract -Token $operatorA.Token -WorkspaceId $workspaceA1.Id
    $viewerBeforeDisable = Invoke-ContractApi -Contract $contract -RouteKey "me" -Token $viewerA.Token
    Assert-ApiSuccess -Response $viewerBeforeDisable -Action "viewer session before membership disable" -Expected @(200)
    $auditorAuditBeforeRevoke = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $auditorA.Token
    Assert-ApiSuccess -Response $auditorAuditBeforeRevoke -Action "auditor audit-read capability before session revoke" -Expected @(200)
    $viewerMembershipId = $viewerA.Memberships[([string]$workspaceA1.Number)]
    $disableMembership = Invoke-ContractApi -Contract $contract -RouteKey "membership_disable" -Token $ownerA.Token -Replacements @{ membership_id = $viewerMembershipId }
    Assert-ApiSuccess -Response $disableMembership -Action "owner membership disable" -Expected @(200, 204)
    $viewerAfterDisable = Invoke-ContractApi -Contract $contract -RouteKey "me" -Token $viewerA.Token
    Assert-ApiDenied -Response $viewerAfterDisable -Action "disabled membership session"

    $revokeSession = Invoke-ContractApi -Contract $contract -RouteKey "session_revoke" -Token $ownerA.Token -Replacements @{ session_id = $auditorA.SessionId }
    Assert-ApiSuccess -Response $revokeSession -Action "owner session revoke" -Expected @(200, 204)
    $auditorAfterRevoke = Invoke-ContractApi -Contract $contract -RouteKey "me" -Token $auditorA.Token
    Assert-ApiDenied -Response $auditorAfterRevoke -Action "revoked session"

    $auditResponse = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $ownerA.Token
    Assert-ApiSuccess -Response $auditResponse -Action "owner audit read" -Expected @(200)
    $auditEvents = @(Get-ResponseItems -Json $auditResponse.Json)
    Assert-Condition -Condition ($auditEvents.Count -ge 1) -Message "audit endpoint returned no events after authenticated and sensitive operations"
    $auditTypes = @($auditEvents | ForEach-Object { (Get-EventType -Event $_).ToLowerInvariant() })
    foreach ($requiredEvent in @($contract.required_audit_events | ForEach-Object { ([string]$_).ToLowerInvariant() })) {
        Assert-Condition -Condition ($auditTypes -contains $requiredEvent) -Message "audit evidence is missing event '$requiredEvent'"
    }

    $auditIds = @($auditEvents | ForEach-Object { Get-EventId -Event $_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    Assert-Condition -Condition ($auditIds.Count -eq (@($auditIds | Sort-Object -Unique)).Count) -Message "audit response contains duplicate event ids"
    $auditDeleteTarget = $auditIds | Select-Object -First 1
    $auditDelete = Invoke-ContractApi -Contract $contract -RouteKey "audit_delete_probe" -Token $ownerA.Token -Replacements @{ event_id = $auditDeleteTarget }
    Assert-ApiStatus -Response $auditDelete -Expected @(401, 403, 404, 405) -Action "audit-event deletion probe"
    $auditAfterDeleteProbe = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $ownerA.Token
    Assert-ApiSuccess -Response $auditAfterDeleteProbe -Action "owner audit read after deletion probe" -Expected @(200)
    $auditEventsAfterProbe = @(Get-ResponseItems -Json $auditAfterDeleteProbe.Json)
    $auditIdsAfterProbe = @($auditEventsAfterProbe | ForEach-Object { Get-EventId -Event $_ })
    foreach ($auditId in $auditIds) {
        Assert-Condition -Condition ($auditIdsAfterProbe -contains $auditId) -Message "audit event $auditId disappeared after a denied deletion probe"
    }

    foreach ($role in @("owner", "admin")) {
        $principal = $tenantA.Users[$role]
        $auditRead = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $principal.Token
        Assert-ApiSuccess -Response $auditRead -Action "$role audit-read capability" -Expected @(200)
    }
    foreach ($role in @("builder", "operator")) {
        $principal = $tenantA.Users[$role]
        $auditRead = Invoke-ContractApi -Contract $contract -RouteKey "audit_list" -Token $principal.Token
        Assert-ApiDenied -Response $auditRead -Action "$role audit-read attempt"
    }

    Write-Output "T-01 E2E PASS: two tenants, two workspaces each, six canonical roles, scope denials, disabled membership/session denial, F01 flow, and append-only audit evidence verified."
} finally {
    if ($tempFixture -and (Test-Path -LiteralPath $tempFixture)) {
        Remove-Item -LiteralPath $tempFixture -Force
    }
    if ($started -and -not $KeepRunning) {
        try {
            $null = Invoke-Compose -DockerPath $dockerExe -ComposePrefix $composePrefix -Arguments @("down", "--remove-orphans")
            Write-Output "T-01 Compose services stopped; the named PostgreSQL volume was preserved."
        } catch {
            Write-Warning "T-01 cleanup failed. Run 'docker compose --project-name $projectName --env-file .env --file docker-compose.yml down --remove-orphans' after reviewing the original failure."
        }
    } elseif ($started -and $KeepRunning) {
        Write-Output "T-01 services remain running by request. Stop only this project with: docker compose --project-name $projectName --env-file .env --file docker-compose.yml down --remove-orphans"
    }
}
