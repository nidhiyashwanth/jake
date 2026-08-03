[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$contractPath = Join-Path $repoRoot "tests\workflows\contract.json"
$fixtureRoot = Join-Path $repoRoot "tests\workflows\fixtures"
$browserSmokePath = Join-Path $repoRoot "tests\workflows\browser_smoke.py"
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$envTemplate = Join-Path $repoRoot ".env.example"
$storageGuardPath = Join-Path $repoRoot "scripts\check-docker-storage.ps1"
$projectName = "ai-ops-platform-w01"

# Alternate ports prevent this verifier from accidentally talking to another
# Compose project. The container-to-container database URL remains unchanged.
$backendPort = 18002
$frontendPort = 13002
$postgresPort = 15434
$apiBaseUrl = "http://localhost:$backendPort"
$frontendBaseUrl = "http://localhost:$frontendPort"

$script:contract = $null
$script:dockerExe = $null
$script:composePrefix = @()
$script:started = $false
$script:environmentConfigured = $false
$script:previousEnvironment = @{}
$script:hadEnvironment = @{}
$portEnvironment = [ordered]@{
    BACKEND_PORT = [string]$backendPort
    FRONTEND_PORT = [string]$frontendPort
    POSTGRES_PORT = [string]$postgresPort
    NEXT_PUBLIC_API_BASE_URL = $apiBaseUrl
    ALLOWED_ORIGINS = "$frontendBaseUrl,http://localhost:3000"
}

function Assert-Condition {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Message
    )

    if (-not $Condition) {
        throw "W-01 assertion failed: $Message Repair: inspect the first failing contract action and the named service logs. Response bodies are intentionally withheld."
    }
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Description
    )

    try {
        return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
    } catch {
        throw "W-01 static contract is not valid JSON for ${Description}: $Path"
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
    return $true
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
        throw "W-01 contract gap: $Action succeeded but did not return a stable id. Expected one of: $($CandidatePaths -join ', ')."
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
        throw "W-01 contract is missing route '$RouteKey'."
    }
    $route = $routeProperty.Value
    $path = [string]$route.path
    foreach ($replacementKey in $Replacements.Keys) {
        $path = $path.Replace("{$replacementKey}", [string]$Replacements[$replacementKey])
    }
    if ($path -match '\{[^}]+\}') {
        throw "W-01 route '$RouteKey' still has an unresolved path parameter: $path"
    }
    return [pscustomobject]@{
        Method = [string]$route.method
        Path = $path
    }
}

function Assert-ApiStatus {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][int[]]$Expected,
        [Parameter(Mandatory)][string]$Action
    )

    if ($Expected -notcontains [int]$Response.Status) {
        throw "W-01 contract failure: $Action returned HTTP $($Response.Status); expected $($Expected -join ', '). The response body is intentionally withheld."
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
        [Parameter(Mandatory)][string]$Action
    )

    $codes = @($script:contract.denial_status_codes | ForEach-Object { [int]$_ })
    Assert-ApiStatus -Response $Response -Expected $codes -Action "$Action (scope or RBAC denial)"
}

function Get-ErrorCode {
    param([AllowNull()][object]$Json)

    return Get-FirstValue -Object $Json -CandidatePaths @("error.code", "code", "detail.code")
}

function Get-ErrorMessage {
    param([AllowNull()][object]$Json)

    return Get-FirstValue -Object $Json -CandidatePaths @("error.message", "message", "detail.message", "detail")
}

function Assert-ErrorEnvelope {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Action
    )

    $code = Get-ErrorCode -Json $Response.Json
    $message = Get-ErrorMessage -Json $Response.Json
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$code)) -Message "$Action did not return a stable error code"
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$message)) -Message "$Action did not return a repairable error message"
}

function Get-FailureReasons {
    param([AllowNull()][object]$Json)

    $value = Get-FirstValue -Object $Json -CandidatePaths @(
        [string]$script:contract.response_contract.evaluation_failure_reason_paths[0],
        [string]$script:contract.response_contract.evaluation_failure_reason_paths[1],
        [string]$script:contract.response_contract.evaluation_failure_reason_paths[2],
        [string]$script:contract.response_contract.evaluation_failure_reason_paths[3],
        [string]$script:contract.response_contract.evaluation_failure_reason_paths[4]
    )
    if ($null -eq $value) {
        return @()
    }
    if ($value -is [System.Array]) {
        return @($value | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    return @([string]$value)
}

function Convert-ToBoolean {
    param([AllowNull()][object]$Value)

    if ($Value -is [bool]) {
        return [bool]$Value
    }
    return [string]::Equals([string]$Value, "true", [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-Sha256 {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory)][string]$Action
    )

    Assert-Condition -Condition ([string]$Value -match '^[0-9a-fA-F]{64}$') -Message "$Action did not return a canonical 64-character SHA-256 hash"
}

function Assert-WorkspaceResponse {
    param(
        [Parameter(Mandatory)]$Json,
        [Parameter(Mandatory)][string]$WorkspaceId,
        [Parameter(Mandatory)][string]$Action
    )

    $returnedWorkspace = Get-FirstValue -Object $Json -CandidatePaths @(
        [string]$script:contract.response_contract.workspace_id_paths[0],
        [string]$script:contract.response_contract.workspace_id_paths[1],
        [string]$script:contract.response_contract.workspace_id_paths[2]
    )
    Assert-Condition -Condition ([string]$returnedWorkspace -eq $WorkspaceId) -Message "$Action did not expose the active workspace scope"
}

function Assert-GraphShape {
    param(
        [Parameter(Mandatory)]$Graph,
        [Parameter(Mandatory)][string]$Action
    )

    $nodes = @($Graph.nodes)
    $edges = @($Graph.edges)
    $schemaVersion = Get-JsonValue -Object $Graph -Path "schema_version"
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$schemaVersion)) -Message "$Action must declare an explicit schema_version"
    Assert-Condition -Condition ($nodes.Count -gt 0) -Message "$Action must contain at least one node"
    Assert-Condition -Condition ($edges.Count -gt 0) -Message "$Action must contain at least one edge"

    $nodeKeys = @{}
    $triggerCount = 0
    $terminalTypes = @("halt", "notify")
    $nodeTypeProperties = $script:contract.node_types.PSObject.Properties
    foreach ($node in $nodes) {
        $key = [string](Get-JsonValue -Object $node -Path "key")
        Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($key)) -Message "$Action contains a node with an empty key"
        Assert-Condition -Condition (-not $nodeKeys.ContainsKey($key)) -Message "$Action contains duplicate node key '$key'"
        $nodeKeys[$key] = $true

        $type = [string](Get-JsonValue -Object $node -Path "type")
        $typeProperty = $nodeTypeProperties | Where-Object { $_.Name -eq $type } | Select-Object -First 1
        Assert-Condition -Condition ($null -ne $typeProperty) -Message "$Action contains unknown node type '$type'"
        if ($type -eq "trigger") {
            $triggerCount++
        }
        $config = Get-JsonValue -Object $node -Path "config"
        Assert-Condition -Condition ($null -ne $config) -Message "$Action node '$key' is missing its config object"
        foreach ($requiredConfig in @($typeProperty.Value.required_config | ForEach-Object { [string]$_ })) {
            $configValue = Get-JsonValue -Object $config -Path $requiredConfig
            Assert-Condition -Condition (Test-ValuePresent -Value $configValue) -Message "$Action node '$key' is missing required config '$requiredConfig'"
        }
        if ($type -eq "llm") {
            $outputSchema = Get-JsonValue -Object $config -Path "output_schema"
            Assert-Condition -Condition ($null -ne $outputSchema -and [string](Get-JsonValue -Object $outputSchema -Path "type") -eq "object") -Message "$Action llm node '$key' must carry a JSON object output_schema"
            $promptKey = [string](Get-JsonValue -Object $config -Path "prompt_key")
            $modelConfigKey = [string](Get-JsonValue -Object $config -Path "model_config_key")
            $promptMatch = @($Graph.prompts | Where-Object { [string]$_.key -eq $promptKey })
            $modelMatch = @($Graph.model_configs | Where-Object { [string]$_.key -eq $modelConfigKey })
            Assert-Condition -Condition ($promptMatch.Count -eq 1) -Message "$Action llm node '$key' references a prompt that is not defined exactly once"
            Assert-Condition -Condition ($modelMatch.Count -eq 1) -Message "$Action llm node '$key' references a model config that is not defined exactly once"
        }
    }
    Assert-Condition -Condition ($triggerCount -eq 1) -Message "$Action must contain exactly one trigger node"

    $thresholdKeys = @($Graph.thresholds | ForEach-Object { [string]$_.key })
    foreach ($scoreNode in @($nodes | Where-Object { [string]$_.type -eq "score" })) {
        $thresholdKey = [string](Get-JsonValue -Object $scoreNode -Path "config.threshold_key")
        Assert-Condition -Condition ($thresholdKeys -contains $thresholdKey) -Message "$Action score node '$($scoreNode.key)' references an undefined threshold"
    }

    $edgePairs = @{}
    $outgoing = @{}
    $incoming = @{}
    $indegree = @{}
    $adjacency = @{}
    foreach ($key in $nodeKeys.Keys) {
        $indegree[$key] = 0
        $adjacency[$key] = @()
        $outgoing[$key] = 0
        $incoming[$key] = 0
    }
    foreach ($edge in $edges) {
        $source = [string](Get-JsonValue -Object $edge -Path "source")
        $target = [string](Get-JsonValue -Object $edge -Path "target")
        Assert-Condition -Condition ($nodeKeys.ContainsKey($source) -and $nodeKeys.ContainsKey($target)) -Message "$Action contains an edge reference to a missing node"
        $pair = "$source`n$target"
        Assert-Condition -Condition (-not $edgePairs.ContainsKey($pair)) -Message "$Action contains a duplicate directed edge '$source' -> '$target'"
        $edgePairs[$pair] = $true
        $adjacency[$source] = @($adjacency[$source]) + @($target)
        $indegree[$target] = [int]$indegree[$target] + 1
        $outgoing[$source] = [int]$outgoing[$source] + 1
        $incoming[$target] = [int]$incoming[$target] + 1
    }

    $queue = New-Object System.Collections.Queue
    foreach ($key in $nodeKeys.Keys) {
        if ([int]$indegree[$key] -eq 0) {
            $queue.Enqueue($key)
        }
    }
    $visited = 0
    while ($queue.Count -gt 0) {
        $current = [string]$queue.Dequeue()
        $visited++
        foreach ($nextKey in @($adjacency[$current])) {
            $indegree[$nextKey] = [int]$indegree[$nextKey] - 1
            if ([int]$indegree[$nextKey] -eq 0) {
                $queue.Enqueue($nextKey)
            }
        }
    }
    Assert-Condition -Condition ($visited -eq $nodeKeys.Count) -Message "$Action contains a directed cycle"

    $terminalNodes = @($nodeKeys.Keys | Where-Object { [int]$outgoing[$_] -eq 0 })
    $hasAllowedTerminal = $false
    foreach ($terminalKey in $terminalNodes) {
        $terminalNode = $nodes | Where-Object { [string]$_.key -eq [string]$terminalKey } | Select-Object -First 1
        if ($terminalTypes -contains [string]$terminalNode.type) {
            $hasAllowedTerminal = $true
        }
    }
    Assert-Condition -Condition $hasAllowedTerminal -Message "$Action must have a halt or notify terminal"
}

function Copy-JsonObject {
    param([Parameter(Mandatory)]$Object)

    return (($Object | ConvertTo-Json -Depth 50 -Compress) | ConvertFrom-Json)
}

function Get-GraphFixture {
    param([Parameter(Mandatory)][string]$FixtureName)

    $path = Join-Path $fixtureRoot $FixtureName
    $fixture = Read-JsonFile -Path $path -Description "fixture $FixtureName"
    if ($null -eq $fixture.base_fixture) {
        return $fixture
    }

    $basePath = Join-Path $fixtureRoot ([string]$fixture.base_fixture)
    $graph = Copy-JsonObject -Object (Read-JsonFile -Path $basePath -Description "base fixture $($fixture.base_fixture)")
    $mutation = $fixture.mutation
    switch ([string]$mutation.kind) {
        "replace_node_type" {
            $node = @($graph.nodes | Where-Object { [string]$_.key -eq [string]$mutation.node_key }) | Select-Object -First 1
            Assert-Condition -Condition ($null -ne $node) -Message "fixture mutation could not find node '$($mutation.node_key)'"
            $node.type = [string]$mutation.value
        }
        "replace_edge_target" {
            $edge = @($graph.edges | Where-Object { [string]$_.id -eq [string]$mutation.edge_id }) | Select-Object -First 1
            Assert-Condition -Condition ($null -ne $edge) -Message "fixture mutation could not find edge '$($mutation.edge_id)'"
            $edge.target = [string]$mutation.value
        }
        "append_edge" {
            $edges = @($graph.edges)
            $edges += $mutation.edge
            $graph.edges = $edges
        }
        "remove_node_config" {
            $node = @($graph.nodes | Where-Object { [string]$_.key -eq [string]$mutation.node_key }) | Select-Object -First 1
            Assert-Condition -Condition ($null -ne $node) -Message "fixture mutation could not find node '$($mutation.node_key)'"
            $node.config.PSObject.Properties.Remove([string]$mutation.property)
        }
        default {
            throw "W-01 fixture mutation kind is unsupported: $($mutation.kind)"
        }
    }
    return $graph
}

function Assert-NoForbiddenVerifierCode {
    $scriptText = Get-Content -LiteralPath $PSCommandPath -Raw
    $forbiddenPatterns = @(
        '(?i)\bpsql\b',
        '(?i)\bsqlite\b',
        '(?i)\bdocker\s+exec\b',
        '(?i)\bInvoke-SqlCmd\b',
        '(?i)\bNpgsql\b',
        '(?i)\bpsycopg\b',
        '(?i)\bSqlConnection\b'
    )
    foreach ($pattern in $forbiddenPatterns) {
        Assert-Condition -Condition ($scriptText -notmatch $pattern) -Message "verifier contains a forbidden direct-storage or container-shell operation"
    }
    Assert-Condition -Condition ($scriptText -match '--env-file') -Message "verifier must use the repository Compose env-file boundary"
    Assert-Condition -Condition ($scriptText -match 'check-docker-storage') -Message "verifier must invoke the Docker storage guard"
    Assert-Condition -Condition ($scriptText -match 'Invoke-WebRequest') -Message "verifier must exercise the HTTP boundary"
    Assert-Condition -Condition ($scriptText -match 'browser_smoke\.py') -Message "verifier must invoke the tracked browser smoke"
    Assert-Condition -Condition ($scriptText -match '\$StaticOnly') -Message "verifier must expose a static-only path"
}

function Test-StaticContract {
    foreach ($requiredPath in @($contractPath, $browserSmokePath, $composeFile, $envTemplate, $storageGuardPath)) {
        Assert-Condition -Condition (Test-Path -LiteralPath $requiredPath -PathType Leaf) -Message "required tracked W-01 verification file is missing: $requiredPath"
    }
    $loadedContract = Read-JsonFile -Path $contractPath -Description "W-01 contract"
    $script:contract = $loadedContract
    foreach ($fixtureName in @(
        [string]$loadedContract.fixtures.valid_definition,
        [string]$loadedContract.fixtures.evaluation_suites
    )) {
        $fixturePath = Join-Path $fixtureRoot $fixtureName
        Assert-Condition -Condition (Test-Path -LiteralPath $fixturePath -PathType Leaf) -Message "required W-01 fixture is missing: $fixturePath"
    }
    foreach ($fixtureName in @($loadedContract.fixtures.invalid_cases | ForEach-Object { [string]$_ })) {
        $fixturePath = Join-Path $fixtureRoot $fixtureName
        Assert-Condition -Condition (Test-Path -LiteralPath $fixturePath -PathType Leaf) -Message "required W-01 invalid fixture is missing: $fixturePath"
    }

    Assert-Condition -Condition ([string]$loadedContract.contract_version -eq "w01.http.v1") -Message "contract.json has an unexpected contract_version"
    $expectedRoles = @("owner", "admin", "builder", "operator", "viewer", "auditor")
    $actualRoles = @($loadedContract.canonical_roles | ForEach-Object { [string]$_ })
    Assert-Condition -Condition ((($actualRoles | Sort-Object) -join ",") -eq (($expectedRoles | Sort-Object) -join ",")) -Message "contract.json must contain exactly the canonical role set"
    Assert-Condition -Condition ([int]$loadedContract.workspace_count -ge 2) -Message "contract.json must exercise at least two workspaces"

    foreach ($statusSet in @(
        @{ Name = "denial_status_codes"; Values = @($loadedContract.denial_status_codes | ForEach-Object { [int]$_ }); Required = @(403) },
        @{ Name = "validation_status_codes"; Values = @($loadedContract.validation_status_codes | ForEach-Object { [int]$_ }); Required = @(422) },
        @{ Name = "immutable_status_codes"; Values = @($loadedContract.immutable_status_codes | ForEach-Object { [int]$_ }); Required = @(409) },
        @{ Name = "publish_gate_denial_status_codes"; Values = @($loadedContract.publish_gate_denial_status_codes | ForEach-Object { [int]$_ }); Required = @(409) },
        @{ Name = "audit_delete_status_codes"; Values = @($loadedContract.audit_delete_status_codes | ForEach-Object { [int]$_ }); Required = @(405) }
    )) {
        foreach ($requiredCode in $statusSet.Required) {
            Assert-Condition -Condition ($statusSet.Values -contains $requiredCode) -Message "contract.json $($statusSet.Name) must include HTTP $requiredCode"
        }
    }

    $requiredRoutes = @(
        "health", "dev_login", "context_set", "membership_create", "audit_list", "audit_delete_probe",
        "workflow_list", "workflow_create", "workflow_detail", "workflow_version_create",
        "workflow_version_detail", "workflow_version_patch", "workflow_validate",
        "workflow_evaluation_run", "workflow_publish", "workflow_graph"
    )
    $allowedMethods = @("GET", "POST", "PATCH", "DELETE")
    foreach ($routeKey in $requiredRoutes) {
        $routeProperty = $loadedContract.routes.PSObject.Properties[$routeKey]
        Assert-Condition -Condition ($null -ne $routeProperty) -Message "contract.json is missing route '$routeKey'"
        Assert-Condition -Condition ($allowedMethods -contains ([string]$routeProperty.Value.method).ToUpperInvariant()) -Message "route '$routeKey' has an unsupported HTTP method"
        Assert-Condition -Condition ([string]$routeProperty.Value.path -like "/api/*") -Message "route '$routeKey' must be an API path"
    }
    Assert-Condition -Condition ([string]$loadedContract.routes.workflow_publish.method -eq "POST") -Message "publish must be an explicit POST transition"
    Assert-Condition -Condition ([string]$loadedContract.routes.workflow_evaluation_run.path -like "*/evaluation-runs") -Message "evaluation must be a durable evaluation-run route"

    $expectedNodeTypes = @("trigger", "fetch", "parse", "classify", "extract", "rule", "score", "llm", "tool", "approve", "notify", "halt")
    $actualNodeTypes = @($loadedContract.node_types.PSObject.Properties | ForEach-Object { [string]$_.Name })
    Assert-Condition -Condition ((($actualNodeTypes | Sort-Object) -join ",") -eq (($expectedNodeTypes | Sort-Object) -join ",")) -Message "contract.json must declare exactly the twelve W-01 node types"
    foreach ($nodeType in $expectedNodeTypes) {
        $nodeSchema = $loadedContract.node_types.PSObject.Properties[$nodeType].Value
        Assert-Condition -Condition (@($nodeSchema.required_config).Count -gt 0) -Message "node type '$nodeType' must declare required config fields"
    }
    Assert-Condition -Condition (@($loadedContract.graph_invariants).Count -ge 10) -Message "contract.json must record the deterministic graph invariants"
    Assert-Condition -Condition (@($loadedContract.required_audit_events).Count -ge 8) -Message "contract.json must require workflow audit evidence"

    $clientForbidden = @($loadedContract.evaluation.client_may_not_supply | ForEach-Object { [string]$_ })
    foreach ($forbiddenField in @("passed", "failure_reasons", "metrics", "version_hash")) {
        Assert-Condition -Condition ($clientForbidden -contains $forbiddenField) -Message "evaluation contract must forbid client-supplied '$forbiddenField'"
    }
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$loadedContract.evaluation.failure_suite_key)) -Message "evaluation contract is missing a failing suite key"
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$loadedContract.evaluation.passing_suite_key)) -Message "evaluation contract is missing a passing suite key"
    Assert-Condition -Condition (@($loadedContract.response_contract.evaluation_version_hash_paths).Count -gt 0) -Message "evaluation response contract must expose the evaluated version hash"
    foreach ($responseCollection in @("nodes_paths", "edges_paths", "thresholds_paths", "prompts_paths", "model_configs_paths")) {
        Assert-Condition -Condition (@(Get-JsonValue -Object $loadedContract.response_contract -Path $responseCollection).Count -gt 0) -Message "response contract is missing $responseCollection"
    }

    $validGraph = Get-GraphFixture -FixtureName ([string]$loadedContract.fixtures.valid_definition)
    Assert-GraphShape -Graph $validGraph -Action "valid W-01 fixture"
    $validNodeTypes = @($validGraph.nodes | ForEach-Object { [string]$_.type } | Sort-Object -Unique)
    foreach ($nodeType in $expectedNodeTypes) {
        Assert-Condition -Condition ($validNodeTypes -contains $nodeType) -Message "valid W-01 fixture must exercise node type '$nodeType'"
    }

    foreach ($fixtureName in @($loadedContract.fixtures.invalid_cases | ForEach-Object { [string]$_ })) {
        $invalidGraph = Get-GraphFixture -FixtureName $fixtureName
        $invalidPassed = $true
        try {
            Assert-GraphShape -Graph $invalidGraph -Action "invalid fixture $fixtureName"
        } catch {
            $invalidPassed = $false
        }
        Assert-Condition -Condition (-not $invalidPassed) -Message "invalid fixture '$fixtureName' unexpectedly satisfies the local DAG/schema contract"
    }

    $evaluationSuites = Read-JsonFile -Path (Join-Path $fixtureRoot ([string]$loadedContract.fixtures.evaluation_suites)) -Description "evaluation suite fixture"
    $suiteKeys = @($evaluationSuites.suites | ForEach-Object { [string]$_.key })
    Assert-Condition -Condition ($suiteKeys -contains [string]$loadedContract.evaluation.failure_suite_key) -Message "evaluation suite fixture is missing the failing server-owned suite"
    Assert-Condition -Condition ($suiteKeys -contains [string]$loadedContract.evaluation.passing_suite_key) -Message "evaluation suite fixture is missing the passing server-owned suite"
    $fixtureForbidden = @($evaluationSuites.client_result_fields_forbidden | ForEach-Object { [string]$_ })
    foreach ($forbiddenField in $clientForbidden) {
        Assert-Condition -Condition ($fixtureForbidden -contains $forbiddenField) -Message "evaluation fixture must repeat the client-result prohibition for '$forbiddenField'"
    }

    $scriptTokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$scriptTokens, [ref]$parseErrors) | Out-Null
    Assert-Condition -Condition (@($parseErrors).Count -eq 0) -Message "verify-workflows.ps1 has PowerShell parse errors"
    Assert-NoForbiddenVerifierCode

    $browserText = Get-Content -LiteralPath $browserSmokePath -Raw
    foreach ($requiredBrowserText in @("sync_playwright", "data-read-only", "draggable", "authorization", "x-workspace-id", "Publish workflow")) {
        Assert-Condition -Condition ($browserText -match [regex]::Escape($requiredBrowserText)) -Message "browser smoke is missing required evidence marker '$requiredBrowserText'"
    }
    Assert-Condition -Condition ($browserText -notmatch '(?i)response\.body|page\.request|\.content\(\)') -Message "browser smoke must not read or dump response bodies"

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
    if (Test-Path -LiteralPath $knownPath -PathType Leaf) {
        $dockerBin = Split-Path -Parent $knownPath
        if (($env:Path -split ';') -notcontains $dockerBin) {
            $env:Path = "$dockerBin;$env:Path"
        }
        return $knownPath
    }
    throw "W-01 prerequisite: Docker executable was not found. Start Docker Desktop or refresh PATH, then rerun scripts\verify-workflows.ps1."
}

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = @(& $script:dockerExe @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "W-01 Docker command failed for Compose project '$projectName'. Docker output is withheld. Repair: inspect only this project's service health/logs and fix the first failing service."
    }
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)

    Invoke-Docker -Arguments ($script:composePrefix + $Arguments)
}

function Invoke-StorageGuard {
    $powerShellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($null -eq $powerShellCommand) {
        $powerShellCommand = Get-Command powershell -ErrorAction SilentlyContinue
    }
    if ($null -eq $powerShellCommand) {
        throw "W-01 prerequisite: Windows PowerShell was not found for the 32 GB Docker storage guard."
    }
    $guardOutput = @(& $powerShellCommand.Source -NoProfile -ExecutionPolicy Bypass -File $storageGuardPath -MaxGb 32 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "W-01 storage guard blocked the run: Docker storage is at or above the 32 GB budget. Output is withheld."
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$ServiceName,
        [int]$Attempts = 60
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                Write-Output "W-01 $ServiceName ready: GET $Uri"
                return
            }
        } catch {
            # Readiness retries intentionally do not expose response content.
        }
        Start-Sleep -Seconds 2
    }
    throw "W-01 service readiness failed for $ServiceName at $Uri after $Attempts attempts. Response content is withheld. Repair: inspect this project's named Compose service and PostgreSQL health."
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
            throw "W-01 secret-safety failure: $Action contained credential-like text. Response content is withheld."
        }
    }
}

function Invoke-Api {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [AllowNull()][object]$Body = $null,
        [AllowNull()][string]$Token = $null,
        [hashtable]$Headers = @{}
    )

    Add-Type -AssemblyName System.Net.Http
    $uri = "$apiBaseUrl$Path"
    $client = [System.Net.Http.HttpClient]::new()
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $uri)
    try {
        foreach ($headerKey in $Headers.Keys) {
            $null = $request.Headers.TryAddWithoutValidation([string]$headerKey, [string]$Headers[$headerKey])
        }
        if (-not [string]::IsNullOrWhiteSpace($Token)) {
            $null = $request.Headers.TryAddWithoutValidation("Authorization", "Bearer $Token")
        }
        if ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 50 -Compress
            $request.Content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, "application/json")
        }
        try {
            $response = $client.SendAsync($request).GetAwaiter().GetResult()
        } catch {
            throw "W-01 HTTP transport failure for $Method ${Path}: $($_.Exception.Message)"
        }
        $status = [int]$response.StatusCode
        $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        Assert-NoCredentialText -Text $responseText -Action "$Method $Path response"
        $parsed = $null
        if (-not [string]::IsNullOrWhiteSpace($responseText)) {
            try {
                $parsed = $responseText | ConvertFrom-Json
            } catch {
                $parsed = $null
            }
        }
        return [pscustomobject]@{
            Status = $status
            Json = $parsed
        }
    } finally {
        if ($null -ne $request) {
            $request.Dispose()
        }
        $client.Dispose()
    }
}

function Invoke-ContractApi {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$RouteKey,
        [AllowNull()][object]$Body = $null,
        [AllowNull()][string]$Token = $null,
        [hashtable]$Replacements = @{},
        [AllowNull()][string]$WorkspaceId = $null
    )

    $route = Get-ContractRoute -Contract $Contract -RouteKey $RouteKey -Replacements $Replacements
    $headers = @{}
    if (-not [string]::IsNullOrWhiteSpace($WorkspaceId)) {
        $headers["X-Workspace-ID"] = $WorkspaceId
    }
    Invoke-Api -Method $route.Method -Path $route.Path -Body $Body -Token $Token -Headers $headers
}

function Get-Token {
    param([Parameter(Mandatory)]$LoginResponse)

    $token = Get-FirstValue -Object $LoginResponse.Json -CandidatePaths @("access_token", "token", "session.access_token")
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace([string]$token)) -Message "development login did not return a bearer session token"
    return [string]$token
}

function Get-WorkspaceIdFromLogin {
    param(
        [Parameter(Mandatory)]$LoginResponse,
        [Parameter(Mandatory)][string]$Action
    )

    return Get-EntityId -Json $LoginResponse.Json -CandidatePaths @("workspace.id", "workspace_id", "session.workspace_id") -Action $Action
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

function Login-Principal {
    param(
        [Parameter(Mandatory)]$Contract,
        [Parameter(Mandatory)][string]$Email,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$OrganizationName,
        [Parameter(Mandatory)][string]$WorkspaceName,
        [Parameter(Mandatory)][string]$WorkspaceId,
        [Parameter(Mandatory)][string]$Action
    )

    $login = Invoke-ContractApi -Contract $Contract -RouteKey "dev_login" -Body @{
        email = $Email
        name = $Name
        organization_name = $OrganizationName
        workspace_name = $WorkspaceName
    }
    Assert-ApiSuccess -Response $login -Action $Action -Expected @(200)
    $token = Get-Token -LoginResponse $login
    Set-ActiveContext -Contract $Contract -Token $token -WorkspaceId $WorkspaceId
    return $token
}

function Get-VersionHash {
    param([Parameter(Mandatory)]$Json)

    $paths = @($script:contract.response_contract.version_hash_paths | ForEach-Object { [string]$_ })
    return Get-FirstValue -Object $Json -CandidatePaths $paths
}

function Get-VersionStatus {
    param([Parameter(Mandatory)]$Json)

    $paths = @($script:contract.response_contract.status_paths | ForEach-Object { [string]$_ })
    return Get-FirstValue -Object $Json -CandidatePaths $paths
}

function Get-VersionNumber {
    param([Parameter(Mandatory)]$Json)

    $paths = @($script:contract.response_contract.version_number_paths | ForEach-Object { [string]$_ })
    return Get-FirstValue -Object $Json -CandidatePaths $paths
}

function Assert-PublishDenied {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Action
    )

    $codes = @($script:contract.publish_gate_denial_status_codes | ForEach-Object { [int]$_ })
    Assert-ApiStatus -Response $Response -Expected $codes -Action $Action
    Assert-ErrorEnvelope -Response $Response -Action $Action
    $reasons = @(Get-FailureReasons -Json $Response.Json)
    Assert-Condition -Condition ($reasons.Count -gt 0) -Message "$Action did not expose non-empty evaluation failure reasons"
}

function Assert-EvaluationResult {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][bool]$ExpectedPassed,
        [Parameter(Mandatory)][string]$Action,
        [AllowNull()][string]$ExpectedHash = $null
    )

    Assert-ApiSuccess -Response $Response -Action $Action -Expected @(200, 201)
    $passed = Get-FirstValue -Object $Response.Json -CandidatePaths @("passed", "evaluation.passed", "result.passed")
    Assert-Condition -Condition ($null -ne $passed) -Message "$Action did not return an evaluation passed flag"
    Assert-Condition -Condition ((Convert-ToBoolean -Value $passed) -eq $ExpectedPassed) -Message "$Action returned an unexpected evaluation result"
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHash)) {
        $evaluatedHash = Get-FirstValue -Object $Response.Json -CandidatePaths @($script:contract.response_contract.evaluation_version_hash_paths | ForEach-Object { [string]$_ })
        Assert-Sha256 -Value $evaluatedHash -Action "$Action version hash"
        Assert-Condition -Condition ([string]$evaluatedHash -eq [string]$ExpectedHash) -Message "$Action was not bound to the exact current version hash"
    }
    if (-not $ExpectedPassed) {
        $reasons = @(Get-FailureReasons -Json $Response.Json)
        Assert-Condition -Condition ($reasons.Count -gt 0) -Message "$Action did not return failure reasons"
    }
}

function Assert-GraphResponse {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Action
    )

    Assert-ApiSuccess -Response $Response -Action $Action -Expected @(200)
    $nodes = Get-FirstValue -Object $Response.Json -CandidatePaths @("nodes", "graph.nodes", "definition.nodes", "version.definition.nodes")
    $edges = Get-FirstValue -Object $Response.Json -CandidatePaths @("edges", "graph.edges", "definition.edges", "version.definition.edges")
    Assert-Condition -Condition (@($nodes).Count -gt 0) -Message "$Action did not expose graph nodes"
    Assert-Condition -Condition (@($edges).Count -gt 0) -Message "$Action did not expose graph edges"
    $readOnly = Get-FirstValue -Object $Response.Json -CandidatePaths @("read_only", "graph.read_only")
    if ($null -ne $readOnly) {
        Assert-Condition -Condition (Convert-ToBoolean -Value $readOnly) -Message "$Action did not identify the graph as read-only"
    } else {
        $editable = Get-FirstValue -Object $Response.Json -CandidatePaths @("editable", "graph.editable")
        Assert-Condition -Condition ($null -ne $editable -and -not (Convert-ToBoolean -Value $editable)) -Message "$Action did not identify the graph as read-only"
    }
}

function Assert-DefinitionPersistence {
    param(
        [Parameter(Mandatory)]$Json,
        [Parameter(Mandatory)][string]$Action
    )

    foreach ($fieldName in @("nodes", "edges", "thresholds", "prompts", "model_configs")) {
        $paths = @(Get-JsonValue -Object $script:contract.response_contract -Path "${fieldName}_paths" | ForEach-Object { [string]$_ })
        $value = Get-FirstValue -Object $Json -CandidatePaths $paths
        Assert-Condition -Condition (@($value).Count -gt 0) -Message "$Action did not persist a non-empty $fieldName collection"
    }
}

function Invoke-WorkflowHttpE2E {
    param([Parameter(Mandatory)]$Contract)

    $runTag = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmssfff")
    $organizationName = "W01 synthetic organization $runTag"
    $workspaceAName = "W01 workspace A $runTag"
    $workspaceBName = "W01 workspace B $runTag"
    $ownerEmail = "w01-$runTag-owner@example.test"
    $builderEmail = "w01-$runTag-builder@example.test"
    $viewerEmail = "w01-$runTag-viewer@example.test"

    $ownerLoginA = Invoke-ContractApi -Contract $Contract -RouteKey "dev_login" -Body @{
        email = $ownerEmail
        name = "W01 synthetic owner"
        organization_name = $organizationName
        workspace_name = $workspaceAName
    }
    Assert-ApiSuccess -Response $ownerLoginA -Action "W-01 owner workspace A login" -Expected @(200)
    $ownerToken = Get-Token -LoginResponse $ownerLoginA
    $workspaceA = Get-WorkspaceIdFromLogin -LoginResponse $ownerLoginA -Action "W-01 workspace A creation"
    Set-ActiveContext -Contract $Contract -Token $ownerToken -WorkspaceId $workspaceA

    $ownerLoginB = Invoke-ContractApi -Contract $Contract -RouteKey "dev_login" -Body @{
        email = $ownerEmail
        name = "W01 synthetic owner"
        organization_name = $organizationName
        workspace_name = $workspaceBName
    }
    Assert-ApiSuccess -Response $ownerLoginB -Action "W-01 owner workspace B login" -Expected @(200)
    $workspaceB = Get-WorkspaceIdFromLogin -LoginResponse $ownerLoginB -Action "W-01 workspace B creation"
    Assert-Condition -Condition ($workspaceA -ne $workspaceB) -Message "W-01 workspace setup did not create two distinct workspaces"
    Set-ActiveContext -Contract $Contract -Token $ownerToken -WorkspaceId $workspaceA

    foreach ($member in @(
        @{ Email = $builderEmail; Name = "W01 synthetic builder"; Role = "builder" },
        @{ Email = $viewerEmail; Name = "W01 synthetic viewer"; Role = "viewer" }
    )) {
        $membership = Invoke-ContractApi -Contract $Contract -RouteKey "membership_create" -Token $ownerToken -WorkspaceId $workspaceA -Replacements @{ workspace_id = $workspaceA } -Body @{
            email = $member.Email
            name = $member.Name
            role = $member.Role
        }
        Assert-ApiSuccess -Response $membership -Action "W-01 $($member.Role) membership" -Expected @(200, 201)
    }

    $builderToken = Login-Principal -Contract $Contract -Email $builderEmail -Name "W01 synthetic builder" -OrganizationName $organizationName -WorkspaceName $workspaceAName -WorkspaceId $workspaceA -Action "W-01 builder login"
    $viewerToken = Login-Principal -Contract $Contract -Email $viewerEmail -Name "W01 synthetic viewer" -OrganizationName $organizationName -WorkspaceName $workspaceAName -WorkspaceId $workspaceA -Action "W-01 viewer login"
    Set-ActiveContext -Contract $Contract -Token $ownerToken -WorkspaceId $workspaceA

    $workflowCreateBody = [ordered]@{
        key = "w01-$runTag"
        name = "W-01 synthetic compliance workflow $runTag"
        description = "Tracked W-01 contract workflow"
    }
    $workflowCreate = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_create" -Token $builderToken -WorkspaceId $workspaceA -Body $workflowCreateBody
    if ([int]$workflowCreate.Status -eq 404) {
        throw "W-01 integration dependency missing: POST /api/workflows returned HTTP 404 at $apiBaseUrl. The coordinator must add the W-01 workflow API before the full verifier can continue. Response content is withheld."
    }
    Assert-ApiSuccess -Response $workflowCreate -Action "builder draft workflow creation" -Expected @(200, 201)
    $workflowId = Get-EntityId -Json $workflowCreate.Json -CandidatePaths @($Contract.response_contract.workflow_id_paths | ForEach-Object { [string]$_ }) -Action "builder draft workflow creation"
    $versionId = Get-EntityId -Json $workflowCreate.Json -CandidatePaths @($Contract.response_contract.draft_version_id_paths | ForEach-Object { [string]$_ }) -Action "initial draft version creation"
    Assert-WorkspaceResponse -Json $workflowCreate.Json -WorkspaceId $workspaceA -Action "workflow creation"

    $workflowDetail = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_detail" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ workflow_id = $workflowId }
    Assert-ApiSuccess -Response $workflowDetail -Action "builder workflow detail" -Expected @(200)
    Assert-WorkspaceResponse -Json $workflowDetail.Json -WorkspaceId $workspaceA -Action "workflow detail"
    $workflowList = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_list" -Token $builderToken -WorkspaceId $workspaceA
    Assert-ApiSuccess -Response $workflowList -Action "builder workflow list" -Expected @(200)
    $listedIds = @(Get-ResponseItems -Json $workflowList.Json | ForEach-Object { Get-FirstValue -Object $_ -CandidatePaths @("id", "workflow_id", "workflow.id") } | ForEach-Object { [string]$_ })
    Assert-Condition -Condition ($listedIds -contains $workflowId) -Message "workflow list did not return the workspace-scoped draft workflow"

    foreach ($invalidFixture in @($Contract.fixtures.invalid_cases | ForEach-Object { [string]$_ })) {
        $invalidGraph = Get-GraphFixture -FixtureName $invalidFixture
        $invalidPatch = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_patch" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body $invalidGraph
        $validationCodes = @($Contract.validation_status_codes | ForEach-Object { [int]$_ })
        Assert-ApiStatus -Response $invalidPatch -Expected $validationCodes -Action "schema/DAG rejection for $invalidFixture"
        Assert-ErrorEnvelope -Response $invalidPatch -Action "schema/DAG rejection for $invalidFixture"
    }

    $validGraph = Get-GraphFixture -FixtureName ([string]$Contract.fixtures.valid_definition)
    $validPatch = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_patch" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body $validGraph
    Assert-ApiSuccess -Response $validPatch -Action "valid form-driven DAG draft save" -Expected @(200)
    $hashBeforeThresholdEdit = Get-VersionHash -Json $validPatch.Json
    Assert-Sha256 -Value $hashBeforeThresholdEdit -Action "draft version hash"

    $sameVersion = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_detail" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-ApiSuccess -Response $sameVersion -Action "draft version detail" -Expected @(200)
    Assert-DefinitionPersistence -Json $sameVersion.Json -Action "draft version detail"
    $hashFromDetail = Get-VersionHash -Json $sameVersion.Json
    Assert-Sha256 -Value $hashFromDetail -Action "draft version detail hash"
    Assert-Condition -Condition ([string]$hashFromDetail -eq [string]$hashBeforeThresholdEdit) -Message "repeated draft version reads returned different hashes"

    $changedGraph = Copy-JsonObject -Object $validGraph
    $changedGraph.thresholds[0].value = 0.8
    $changedPatch = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_patch" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body $changedGraph
    Assert-ApiSuccess -Response $changedPatch -Action "changed draft threshold save" -Expected @(200)
    $hashAfterThresholdEdit = Get-VersionHash -Json $changedPatch.Json
    Assert-Sha256 -Value $hashAfterThresholdEdit -Action "changed draft version hash"
    Assert-Condition -Condition ([string]$hashAfterThresholdEdit -ne [string]$hashBeforeThresholdEdit) -Message "changing the draft definition did not change its content hash"

    $validation = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_validate" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-ApiSuccess -Response $validation -Action "valid DAG schema validation" -Expected @(200)
    $validFlag = Get-FirstValue -Object $validation.Json -CandidatePaths @("valid", "validation.valid", "result.valid")
    if ($null -ne $validFlag) {
        Assert-Condition -Condition (Convert-ToBoolean -Value $validFlag) -Message "valid DAG schema validation returned valid=false"
    }

    $graphRead = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_graph" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-GraphResponse -Response $graphRead -Action "read-only workflow graph"

    $viewerRead = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_detail" -Token $viewerToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-ApiSuccess -Response $viewerRead -Action "viewer workflow read" -Expected @(200)
    $viewerGraph = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_graph" -Token $viewerToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-GraphResponse -Response $viewerGraph -Action "viewer read-only workflow graph"
    $viewerPatch = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_patch" -Token $viewerToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body $changedGraph
    Assert-ApiDenied -Response $viewerPatch -Action "viewer workflow mutation attempt"

    Set-ActiveContext -Contract $Contract -Token $ownerToken -WorkspaceId $workspaceB
    $workspaceBList = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_list" -Token $ownerToken -WorkspaceId $workspaceB
    Assert-ApiSuccess -Response $workspaceBList -Action "second workspace workflow list" -Expected @(200)
    $workspaceBIds = @(Get-ResponseItems -Json $workspaceBList.Json | ForEach-Object { Get-FirstValue -Object $_ -CandidatePaths @("id", "workflow_id", "workflow.id") } | ForEach-Object { [string]$_ })
    Assert-Condition -Condition ($workspaceBIds -notcontains $workflowId) -Message "workspace B received a workflow created in workspace A"
    $crossWorkspaceDetail = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_detail" -Token $ownerToken -WorkspaceId $workspaceB -Replacements @{ workflow_id = $workflowId }
    Assert-ApiDenied -Response $crossWorkspaceDetail -Action "cross-workspace workflow detail"
    $crossWorkspaceGraph = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_graph" -Token $ownerToken -WorkspaceId $workspaceB -Replacements @{ version_id = $versionId }
    Assert-ApiDenied -Response $crossWorkspaceGraph -Action "cross-workspace graph read"
    Set-ActiveContext -Contract $Contract -Token $builderToken -WorkspaceId $workspaceA

    $publishBeforeEvaluation = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_publish" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body @{}
    Assert-PublishDenied -Response $publishBeforeEvaluation -Action "publish without evaluation"

    $failedEvaluation = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_evaluation_run" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body @{ suite_key = [string]$Contract.evaluation.failure_suite_key }
    Assert-EvaluationResult -Response $failedEvaluation -ExpectedPassed $false -ExpectedHash ([string]$hashAfterThresholdEdit) -Action "failing server-owned evaluation"
    $publishAfterFailure = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_publish" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body @{}
    Assert-PublishDenied -Response $publishAfterFailure -Action "publish after failed evaluation"

    $passingEvaluation = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_evaluation_run" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body @{ suite_key = [string]$Contract.evaluation.passing_suite_key }
    Assert-EvaluationResult -Response $passingEvaluation -ExpectedPassed $true -ExpectedHash ([string]$hashAfterThresholdEdit) -Action "passing server-owned evaluation"
    $published = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_publish" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body @{}
    Assert-ApiSuccess -Response $published -Action "publish after passing exact-version evaluation" -Expected @(200)
    $publishedHash = Get-VersionHash -Json $published.Json
    Assert-Sha256 -Value $publishedHash -Action "published version hash"
    Assert-Condition -Condition ([string]$publishedHash -eq [string]$hashAfterThresholdEdit) -Message "published version hash did not match the evaluated draft hash"
    $publishedStatus = [string](Get-VersionStatus -Json $published.Json)
    Assert-Condition -Condition ($publishedStatus.ToLowerInvariant() -eq "published") -Message "successful publish did not return published status"

    $publishedDetail = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_detail" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-ApiSuccess -Response $publishedDetail -Action "published version detail" -Expected @(200)
    $publishedDetailHash = Get-VersionHash -Json $publishedDetail.Json
    Assert-Condition -Condition ([string]$publishedDetailHash -eq [string]$publishedHash) -Message "published version hash changed on read"
    $publishedDetailStatus = [string](Get-VersionStatus -Json $publishedDetail.Json)
    Assert-Condition -Condition ($publishedDetailStatus.ToLowerInvariant() -eq "published") -Message "published version detail is mutable or not marked published"

    $immutableCodes = @($Contract.immutable_status_codes | ForEach-Object { [int]$_ })
    $republish = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_publish" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body @{}
    Assert-ApiStatus -Response $republish -Expected $immutableCodes -Action "published version republish probe"
    Assert-ErrorEnvelope -Response $republish -Action "published version republish probe"

    $publishedMutation = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_patch" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId } -Body $changedGraph
    Assert-ApiStatus -Response $publishedMutation -Expected $immutableCodes -Action "published version mutation probe"
    Assert-ErrorEnvelope -Response $publishedMutation -Action "published version mutation probe"
    $publishedAfterProbe = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_detail" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ version_id = $versionId }
    Assert-ApiSuccess -Response $publishedAfterProbe -Action "published version detail after mutation probe" -Expected @(200)
    Assert-Condition -Condition ([string](Get-VersionHash -Json $publishedAfterProbe.Json) -eq [string]$publishedHash) -Message "published version hash changed after a rejected mutation"

    $secondVersion = Invoke-ContractApi -Contract $Contract -RouteKey "workflow_version_create" -Token $builderToken -WorkspaceId $workspaceA -Replacements @{ workflow_id = $workflowId } -Body @{}
    Assert-ApiSuccess -Response $secondVersion -Action "new draft version after publish" -Expected @(200, 201)
    $secondVersionId = Get-EntityId -Json $secondVersion.Json -CandidatePaths @($Contract.response_contract.draft_version_id_paths | ForEach-Object { [string]$_ }) -Action "new draft version after publish"
    Assert-Condition -Condition ($secondVersionId -ne $versionId) -Message "new draft version reused the immutable published version id"
    $secondVersionStatus = [string](Get-VersionStatus -Json $secondVersion.Json)
    Assert-Condition -Condition ($secondVersionStatus.ToLowerInvariant() -eq "draft") -Message "new version after publish did not start as draft"

    Set-ActiveContext -Contract $Contract -Token $ownerToken -WorkspaceId $workspaceA
    $auditBeforeDelete = Invoke-ContractApi -Contract $Contract -RouteKey "audit_list" -Token $ownerToken -WorkspaceId $workspaceA
    Assert-ApiSuccess -Response $auditBeforeDelete -Action "W-01 audit read" -Expected @(200)
    $auditEvents = @(Get-ResponseItems -Json $auditBeforeDelete.Json)
    Assert-Condition -Condition ($auditEvents.Count -gt 0) -Message "W-01 audit endpoint returned no events"
    $auditIds = @($auditEvents | ForEach-Object { Get-EventId -Event $_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    Assert-Condition -Condition ($auditIds.Count -eq (@($auditIds | Sort-Object -Unique).Count)) -Message "W-01 audit response contains duplicate event ids"
    $auditActions = @($auditEvents | ForEach-Object { (Get-EventAction -Event $_).ToLowerInvariant() })
    foreach ($requiredAction in @($Contract.required_audit_events | ForEach-Object { ([string]$_).ToLowerInvariant() })) {
        Assert-Condition -Condition ($auditActions -contains $requiredAction) -Message "W-01 audit evidence is missing '$requiredAction'"
    }
    $deleteTarget = $auditIds | Select-Object -First 1
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($deleteTarget)) -Message "W-01 audit response did not expose a deletion-probe id"
    $deleteProbe = Invoke-ContractApi -Contract $Contract -RouteKey "audit_delete_probe" -Token $ownerToken -WorkspaceId $workspaceA -Replacements @{ event_id = $deleteTarget }
    $deleteCodes = @($Contract.audit_delete_status_codes | ForEach-Object { [int]$_ })
    Assert-ApiStatus -Response $deleteProbe -Expected $deleteCodes -Action "append-only audit deletion probe"
    $auditAfterDelete = Invoke-ContractApi -Contract $Contract -RouteKey "audit_list" -Token $ownerToken -WorkspaceId $workspaceA
    Assert-ApiSuccess -Response $auditAfterDelete -Action "W-01 audit read after deletion probe" -Expected @(200)
    $auditIdsAfterDelete = @((Get-ResponseItems -Json $auditAfterDelete.Json) | ForEach-Object { Get-EventId -Event $_ })
    foreach ($auditId in $auditIds) {
        Assert-Condition -Condition ($auditIdsAfterDelete -contains $auditId) -Message "audit event $auditId disappeared after a denied deletion probe"
    }

    Write-Output "W-01 HTTP PASS: two-workspace isolation, form-shaped DAG persistence, schema/cycle/reference rejection, read-only graph, immutable SHA-256 versions, evaluation-gated publish, RBAC denial, and append-only audit evidence verified."
}

function Invoke-BrowserSmoke {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $pythonArgs = @()
    if ($null -eq $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    }
    if ($null -eq $pythonCommand) {
        $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
        }
        if ($null -ne $pythonCommand) {
            $pythonArgs += "-3"
        }
    }
    if ($null -eq $pythonCommand) {
        throw "W-01 integration dependency missing: Python with Playwright is required for tests\workflows\browser_smoke.py."
    }
    $pythonArgs += @(
        $browserSmokePath,
        "--frontend-url",
        $frontendBaseUrl,
        "--contract",
        $contractPath
    )
    $browserOutput = @(& $pythonCommand.Source @pythonArgs 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "W-01 browser integration failed. The browser smoke output is withheld; repair the first missing workflow UI/API boundary and rerun."
    }
    Write-Output "W-01 browser PASS: live form-driven editor, read-only graph, evaluation failure guidance, and scoped workflow requests verified."
}

function Start-W01Compose {
    Assert-Condition -Condition (Test-Path -LiteralPath $envFile -PathType Leaf) -Message "the ignored repository-root .env is required for the real Compose/PostgreSQL path; it was not read or printed"
    Invoke-StorageGuard
    $script:dockerExe = Resolve-DockerExecutable
    $script:composePrefix = @("compose", "--project-name", $projectName, "--env-file", $envFile, "--file", $composeFile)
    foreach ($key in $portEnvironment.Keys) {
        $existing = Get-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
        $script:hadEnvironment[$key] = ($null -ne $existing)
        if ($null -ne $existing) {
            $script:previousEnvironment[$key] = [string]$existing.Value
        }
        Set-Item -LiteralPath "Env:$key" -Value $portEnvironment[$key]
    }
    $script:environmentConfigured = $true
    $null = Invoke-Compose -Arguments @("config", "--quiet")
    $null = Invoke-Compose -Arguments @("up", "-d", "--build")
    $script:started = $true
    Wait-HttpReady -Uri "$apiBaseUrl/api/health" -ServiceName "backend" -Attempts 60
    Wait-HttpReady -Uri $frontendBaseUrl -ServiceName "frontend" -Attempts 60
}

function Stop-W01Compose {
    if ($script:started -and -not $KeepRunning -and $null -ne $script:dockerExe) {
        try {
            $null = Invoke-Compose -Arguments @("down", "--remove-orphans")
            Write-Output "W-01 Compose services stopped; the named PostgreSQL volume was preserved."
            Invoke-StorageGuard
            Write-Output "W-01 storage guard PASS: Docker storage remains within the 32 GB budget."
        } catch {
            Write-Warning "W-01 cleanup failed. Stop only project '$projectName' with docker compose --project-name $projectName --env-file .env --file docker-compose.yml down --remove-orphans."
        }
    } elseif ($script:started -and $KeepRunning) {
        Write-Output "W-01 services remain running by request. Stop only project '$projectName' with docker compose --project-name $projectName --env-file .env --file docker-compose.yml down --remove-orphans"
    }
    if ($script:environmentConfigured) {
        foreach ($key in $portEnvironment.Keys) {
            if ($script:hadEnvironment.ContainsKey($key) -and $script:hadEnvironment[$key]) {
                Set-Item -LiteralPath "Env:$key" -Value $script:previousEnvironment[$key]
            } else {
                Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
            }
        }
    }
}

$exitCode = 0
try {
    $script:contract = Test-StaticContract
    if ($StaticOnly) {
        Write-Output "W-01 STATIC PASS: tracked contract, twelve node schemas, graph fixtures, evaluation prohibitions, PowerShell syntax, storage guard, and browser smoke markers verified."
    } else {
        Start-W01Compose
        $health = Invoke-ContractApi -Contract $script:contract -RouteKey "health"
        Assert-ApiSuccess -Response $health -Action "PostgreSQL-backed API health" -Expected @(200)
        Invoke-WorkflowHttpE2E -Contract $script:contract
        Invoke-BrowserSmoke
        Write-Output "W-01 E2E PASS: real Compose/PostgreSQL HTTP and browser evidence completed."
    }
} catch {
    Write-Error $_.Exception.Message
    $exitCode = 1
} finally {
    Stop-W01Compose
}

if ($exitCode -ne 0) {
    exit $exitCode
}
