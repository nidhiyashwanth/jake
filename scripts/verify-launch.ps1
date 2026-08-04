[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$contractPath = Join-Path $repoRoot "tests\launch\contract.json"
$manifestPath = Join-Path $repoRoot "tests\launch\acceptance-manifest.json"
$roleTourPath = Join-Path $repoRoot "tests\launch\browser_role_tour.py"
$x01Script = Join-Path $repoRoot "scripts\verify-x01.ps1"
$envFile = Join-Path $repoRoot ".env"
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$projectName = "ai-ops-platform-x01"
$frontendUrl = "http://localhost:13006"
$reportDirectory = Join-Path $repoRoot "artifacts\launch"
$reportPath = Join-Path $reportDirectory "acceptance-report.json"
$powerShellCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue }
if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell -ErrorAction SilentlyContinue }
$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $dockerCommand) { $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue }
$started = $false

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "LAUNCH-01 assertion failed: $Message" }
}

function Invoke-PowerShell {
    param([Parameter(Mandatory)][string[]]$Arguments)
    Assert-Condition ($null -ne $script:powerShellCommand) "PowerShell is required for nested release gates"
    & $script:powerShellCommand.Source @Arguments
    if ($LASTEXITCODE -ne 0) { throw "nested PowerShell gate failed" }
}

function Test-StaticContract {
    Assert-Condition (Test-Path -LiteralPath $contractPath -PathType Leaf) "launch contract is missing"
    Assert-Condition (Test-Path -LiteralPath $manifestPath -PathType Leaf) "acceptance manifest is missing"
    $contract = Get-Content -Raw -LiteralPath $contractPath | ConvertFrom-Json
    Assert-Condition ($contract.contract_version -eq "launch.v1") "launch contract version drifted"
    foreach ($relativePath in $contract.required_paths) {
        Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot ([string]$relativePath)) -PathType Leaf) "required launch path is missing: $relativePath"
    }
    foreach ($property in $contract.required_markers.PSObject.Properties) {
        $target = switch ($property.Name) {
            "acceptance" { Join-Path $repoRoot "docs\LAUNCH-ACCEPTANCE.md" }
            "operations" { Join-Path $repoRoot "docs\OPERATIONS-RUNBOOK.md" }
            "roles" { Join-Path $repoRoot "docs\ROLE-WALKTHROUGHS.md" }
            "release" { Join-Path $repoRoot "docs\RELEASE-CHECKLIST.md" }
            default { $null }
        }
        Assert-Condition ($null -ne $target -and (Test-Path -LiteralPath $target -PathType Leaf)) "marker target is missing: $($property.Name)"
        $content = Get-Content -Raw -LiteralPath $target
        foreach ($marker in @($property.Value)) {
            Assert-Condition ($content -match [regex]::Escape([string]$marker)) "launch marker is missing: $marker"
        }
    }
    foreach ($scriptPath in @("scripts\verify-launch.ps1", "scripts\verify-x01.ps1")) {
        $fullPath = Join-Path $repoRoot $scriptPath
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($fullPath, [ref]$tokens, [ref]$errors) | Out-Null
        Assert-Condition ($errors.Count -eq 0) "$scriptPath has PowerShell parse errors"
    }
    return $contract
}

function Test-AcceptanceManifest {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    Assert-Condition ($manifest.schema_version -eq "launch.acceptance.v1") "acceptance manifest version drifted"
    Assert-Condition ($manifest.fixture_class -eq "synthetic-release-candidate") "launch evidence must identify its synthetic fixture boundary"

    Assert-Condition ([bool]$manifest.baseline.signed) "baseline is not signed"
    Assert-Condition ([int]$manifest.baseline.version -ge 1) "baseline version is not positive"
    Assert-Condition ([bool]$manifest.baseline.referenced_by_value_events) "baseline is not bound to value events"

    Assert-Condition ([bool]$manifest.shadow_mode.completed) "shadow mode is incomplete"
    Assert-Condition ([int]$manifest.shadow_mode.observed_business_days -ge 5) "shadow mode is shorter than five business days"
    Assert-Condition ([int]$manifest.shadow_mode.representative_document_types -ge 10) "representative document coverage is incomplete"
    Assert-Condition ([int]$manifest.shadow_mode.weekly_demos -ge 2) "weekly live-data demos are missing"
    Assert-Condition ([bool]$manifest.shadow_mode.worker_failure_injected) "worker failure was not injected"
    Assert-Condition ([bool]$manifest.shadow_mode.worker_recovered_without_duplicate_side_effect) "worker recovery evidence is missing"

    Assert-Condition ([int]$manifest.golden_set.cases -ge 100) "golden set has fewer than 100 cases"
    Assert-Condition ([int]$manifest.golden_set.exceptions -ge 20) "golden set has fewer than 20 exceptions"
    Assert-Condition ([int]$manifest.golden_set.injection_canaries -ge 3) "fewer than three injection canaries are recorded"
    Assert-Condition ([bool]$manifest.golden_set.evaluation_gate_blocks_failed_candidate) "evaluation gate blocking is not evidenced"

    $autoCases = [double]$manifest.oversight.auto_processed_cases
    $sampledCases = [double]$manifest.oversight.sampled_audit_cases
    $sampleRate = if ($autoCases -gt 0) { $sampledCases / $autoCases } else { 0 }
    Assert-Condition ($autoCases -ge 100) "auto-error sample has fewer than 100 cases"
    Assert-Condition ($sampleRate -ge [double]$manifest.oversight.minimum_sample_rate) "sampled audit rate is below the two-percent floor"
    $errorRate = [double]$manifest.oversight.measured_errors / [double]$manifest.oversight.measured_error_sample_size
    Assert-Condition ($errorRate -le [double]$manifest.oversight.target_auto_error_rate) "measured auto error rate exceeds target"
    Assert-Condition ([bool]$manifest.oversight.false_auto_rollback_rehearsed) "false-auto rollback was not rehearsed"

    $window = $manifest.acceptance_window
    $total = [int]$window.total_cases
    $auto = [int]$window.auto_processed
    $reviewed = [int]$window.reviewed
    $halted = [int]$window.halted
    Assert-Condition ([int]$window.business_days -eq 10) "acceptance window is not ten business days"
    Assert-Condition (($auto + $reviewed + $halted) -eq $total) "acceptance routing counts do not reconcile"
    $straightThroughRate = if ($total -gt 0) { [double]$auto / $total } else { 0 }
    Assert-Condition ($straightThroughRate -ge [double]$window.target_straight_through_rate) "straight-through rate is below target"
    Assert-Condition ([int]$window.open_p1_defects -eq 0) "P1 defects remain open"
    Assert-Condition ([int]$window.operators_trained -ge [int]$window.operators_required) "not all operators are trained"
    Assert-Condition ([int]$window.operators_independent -ge [int]$window.operators_required) "operators have not completed an independent tour"

    $ledger = $manifest.ledger
    Assert-Condition (([int]$ledger.auto + [int]$ledger.reviewed + [int]$ledger.halted) -eq [int]$ledger.ingested) "ledger counts do not reconcile"
    Assert-Condition ([int]$ledger.orphan_events -eq 0) "orphan ledger events remain"
    Assert-Condition ([bool]$manifest.audit_pack.generated -and [bool]$manifest.audit_pack.redacted -and [bool]$manifest.audit_pack.access_logged) "audit-pack evidence is incomplete"
    Assert-Condition ([bool]$manifest.handover.runbook_tested_by_non_builder) "non-builder runbook test is missing"
    Assert-Condition ([int]@($manifest.handover.roles_toured).Count -ge 4) "role walkthrough coverage is incomplete"
    Assert-Condition ([bool]$manifest.handover.customer_workflow_owner_recorded) "customer workflow owner is missing"
    foreach ($property in $manifest.release.PSObject.Properties) {
        Assert-Condition ([bool]$property.Value) "release evidence is incomplete: $($property.Name)"
    }

    return [pscustomobject]@{
        fixture_class = $manifest.fixture_class
        business_days = [int]$window.business_days
        total_cases = $total
        auto_processed = $auto
        reviewed = $reviewed
        halted = $halted
        straight_through_rate = [math]::Round($straightThroughRate, 4)
        measured_auto_error_rate = [math]::Round($errorRate, 4)
        sampled_audit_rate = [math]::Round($sampleRate, 4)
        golden_cases = [int]$manifest.golden_set.cases
        golden_exceptions = [int]$manifest.golden_set.exceptions
        injection_canaries = [int]$manifest.golden_set.injection_canaries
        orphan_events = [int]$ledger.orphan_events
    }
}

function Write-AcceptanceReport {
    param([Parameter(Mandatory)]$Summary)
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    $report = [ordered]@{
        contract = "launch.v1"
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
        stack = [ordered]@{ compose_project = $projectName; frontend_url = $frontendUrl; fixture_boundary = "synthetic-release-candidate" }
        acceptance = $Summary
        evidence = @(
            "X-01 Compose/PostgreSQL/migration/browser/recovery gate",
            "LAUNCH-01 browser role tour",
            "Synthetic acceptance manifest recomputation"
        )
    }
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding utf8
}

function Start-ReleaseStack {
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) "ignored .env is required and is never printed"
    Assert-Condition (Test-Path -LiteralPath $composeFile -PathType Leaf) "Compose file is missing"
    Invoke-PowerShell -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $x01Script, "-KeepRunning", "-SkipImageScan")
    $script:started = $true
}

function Invoke-RoleTour {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $python) "Python with Playwright is required for the live role tour"
    & $python.Source $roleTourPath --frontend-url $frontendUrl
    if ($LASTEXITCODE -ne 0) { throw "LAUNCH-01 browser role tour failed" }
}

function Stop-ReleaseStack {
    if (-not $started -or $KeepRunning) {
        if ($started -and $KeepRunning) { Write-Output "LAUNCH-01 services remain running by request; stop only project '$projectName' with its env-file." }
        return
    }
    if ($null -eq $dockerCommand) { Write-Warning "Docker CLI not found for launch cleanup; stop project '$projectName' manually."; return }
    $hadVolumeName = Test-Path -LiteralPath "Env:POSTGRES_VOLUME_NAME"
    $previousVolumeName = if ($hadVolumeName) { [string]$env:POSTGRES_VOLUME_NAME } else { $null }
    try {
        # The parent process does not inherit verify-x01's temporary env
        # overrides. Pin cleanup to the launch-owned volume so an old base
        # Compose/MVP volume can never become a deletion target.
        $env:POSTGRES_VOLUME_NAME = "ai-ops-platform-x01-data"
        & $dockerCommand.Source compose --project-name $projectName --env-file $envFile --file $composeFile down --volumes --remove-orphans | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "docker compose cleanup returned $LASTEXITCODE" }
        Write-Output "LAUNCH-01 cleanup PASS: exact release-candidate Compose project and temporary volume removed."
    } catch { Write-Warning "LAUNCH-01 cleanup failed; stop only project '$projectName' with its env-file." }
    finally {
        if ($hadVolumeName) { $env:POSTGRES_VOLUME_NAME = $previousVolumeName }
        else { Remove-Item -LiteralPath "Env:POSTGRES_VOLUME_NAME" -ErrorAction SilentlyContinue }
    }
}

$exitCode = 0
try {
    $null = Test-StaticContract
    $summary = Test-AcceptanceManifest
    if ($StaticOnly) {
        Write-Output "LAUNCH-01 STATIC PASS: acceptance contract, manifest, handover docs, runbook, support routes, and release checklist verified."
    } else {
        Start-ReleaseStack
        Invoke-RoleTour
        Write-AcceptanceReport -Summary $summary
        Write-Output "LAUNCH-01 ACCEPTANCE PASS: synthetic shadow/live thresholds, golden-set controls, sampled audit, ledger reconciliation, handover evidence, and live browser role tour verified."
    }
} catch {
    Write-Error $_.Exception.Message
    $exitCode = 1
} finally {
    Stop-ReleaseStack
}
if ($exitCode -ne 0) { exit $exitCode }
