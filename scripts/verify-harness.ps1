[CmdletBinding()]
param(
    [ValidateSet('All', 'Instructions', 'State', 'Verification')]
    [string]$Area = 'All'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Message)
    [void]$script:failures.Add($Message)
}

function Require-File {
    param([string]$RelativePath)
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Failure "Missing $RelativePath. Create the required harness artifact before continuing."
        return $null
    }
    return $path
}

function Require-Contains {
    param(
        [string]$RelativePath,
        [string]$Text,
        [string]$Repair
    )
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return
    }
    $content = Get-Content -Raw -LiteralPath $path
    if ($content.IndexOf($Text, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Add-Failure "$RelativePath is missing '$Text'. $Repair"
    }
}

function Test-Instructions {
    $requiredFiles = @(
        'AGENTS.md',
        'CLAUDE.md',
        'README.md',
        'task.md',
        'PROGRESS.md',
        'DECISIONS.md',
        'feature-list.json',
        'docs/ARCHITECTURE-RULES.md',
        'docs/VERIFICATION.md',
        'docs/WORKFLOW.md'
    )

    foreach ($requiredFile in $requiredFiles) {
        [void](Require-File $requiredFile)
    }

    Require-Contains 'AGENTS.md' '## Run it' 'Document the current runnable surface; do not invent an application command.'
    Require-Contains 'AGENTS.md' '## Verify it' 'Document the exact verification commands.'
    Require-Contains 'AGENTS.md' '## Hard constraints' 'Keep global red lines in the routed entry file.'
    Require-Contains 'AGENTS.md' '## Routing map' 'Route detailed guidance to focused topic files.'
    Require-Contains 'AGENTS.md' 'task.md' 'Route the complete-product execution backlog from the entry instructions.'
    Require-Contains 'task.md' '## Master execution prompt' 'Keep the reusable workstream prompt in the repository.'
    Require-Contains 'task.md' '## Work package board' 'Track all product work packages and their evidence state.'
    Require-Contains 'task.md' '## Detailed tasks and Definition of Done' 'Define executable completion checks for product work.'
    [void](Require-File 'scripts/check-secrets.ps1')
    [void](Require-File 'scripts/verify-product.ps1')
    [void](Require-File 'scripts/verify-fresh-session.ps1')
    Require-Contains 'README.md' 'Current operating phase' 'Record the current phase in the project overview.'
    Require-Contains 'README.md' 'AGENTS.md' 'Link the repository entrypoint from the README.'
    Require-Contains 'docs/ARCHITECTURE-RULES.md' 'Source:' 'Add source metadata to topic instructions.'
    Require-Contains 'docs/ARCHITECTURE-RULES.md' 'Applicability:' 'Add applicability metadata to topic instructions.'
    Require-Contains 'docs/ARCHITECTURE-RULES.md' 'Expiry:' 'Add expiry metadata to topic instructions.'
    Require-Contains 'docs/VERIFICATION.md' 'Source:' 'Add source metadata to topic instructions.'
    Require-Contains 'docs/WORKFLOW.md' 'Expiry:' 'Add expiry metadata to topic instructions.'
}

function Test-State {
    $progressPath = Require-File 'PROGRESS.md'
    $decisionsPath = Require-File 'DECISIONS.md'
    $featurePath = Require-File 'feature-list.json'
    $taskPath = Require-File 'task.md'
    if ($null -eq $featurePath) {
        return
    }

    try {
        $featureList = Get-Content -Raw -LiteralPath $featurePath | ConvertFrom-Json
    }
    catch {
        Add-Failure "feature-list.json is not valid JSON. Repair the parse error before changing feature state."
        return
    }

    if ($featureList.wip_limit -ne 1) {
        Add-Failure "feature-list.json must set wip_limit to 1. WIP=1 is the default safety boundary."
    }

    $features = @($featureList.features)
    if ($features.Count -eq 0) {
        Add-Failure 'feature-list.json has no features. Add at least one executable harness task.'
    }

    $validStates = @('not_started', 'active', 'blocked', 'passing')
    $activeCount = 0
    foreach ($feature in $features) {
        foreach ($property in @('id', 'behavior', 'verification', 'state', 'evidence')) {
            if (-not ($feature.PSObject.Properties.Name -contains $property)) {
                Add-Failure "Feature $($feature.id) is missing '$property'. Every row needs behavior, verification, state, and evidence."
            }
        }

        if ($feature.state -notin $validStates) {
            Add-Failure "Feature $($feature.id) has invalid state '$($feature.state)'. Use not_started, active, blocked, or passing."
        }
        if ($feature.state -eq 'active') {
            $activeCount++
        }
        if ($feature.state -eq 'passing' -and [string]::IsNullOrWhiteSpace([string]$feature.evidence)) {
            Add-Failure "Feature $($feature.id) is marked passing without evidence. Attach a command result, commit, or artifact."
        }
        if ([string]::IsNullOrWhiteSpace([string]$feature.behavior) -or [string]::IsNullOrWhiteSpace([string]$feature.verification)) {
            Add-Failure "Feature $($feature.id) needs non-empty behavior and verification fields."
        }
    }

    if ($activeCount -gt 1) {
        Add-Failure "feature-list.json has $activeCount active features. WIP=1 allows only one active feature."
    }
    if ($null -ne $taskPath) {
        $taskContent = Get-Content -Raw -LiteralPath $taskPath
        foreach ($activeFeature in @($features | Where-Object { $_.state -eq 'active' })) {
            $taskPattern = "(?m)^\|\s*$($activeFeature.id)\s*\|.*\|\s*active\s*\|"
            if ($taskContent -notmatch $taskPattern) {
                Add-Failure "Active feature $($activeFeature.id) is not marked active in task.md. Keep the feature list and detailed task board aligned."
            }
        }
    }
    if ($null -ne $progressPath) {
        Require-Contains 'PROGRESS.md' 'feature-list.json' 'Point the handoff document to the executable feature list.'
        Require-Contains 'PROGRESS.md' 'WIP=1' 'Record the active-work limit in the handoff document.'
    }
    if ($null -ne $decisionsPath) {
        Require-Contains 'DECISIONS.md' 'D-001' 'Record at least one durable decision with a stable identifier.'
    }
}

function Test-Verification {
    [void](Require-File 'scripts/verify-harness.ps1')
    Require-Contains 'AGENTS.md' 'Definition of Done' 'State the completion gate in the entry instructions.'
    Require-Contains 'AGENTS.md' 'scripts/verify-harness.ps1' 'Expose the executable verifier to a fresh session.'
    Require-Contains 'docs/VERIFICATION.md' 'Layer 1' 'Define the static verification layer.'
    Require-Contains 'docs/VERIFICATION.md' 'Layer 2' 'Define the runtime verification layer.'
    Require-Contains 'docs/VERIFICATION.md' 'Layer 3' 'Define the end-to-end verification layer.'
    Require-Contains 'docs/VERIFICATION.md' 'missing runtime command' 'Record unavailable checks as gaps instead of fake passes.'

    $envPath = Join-Path $repoRoot '.env'
    if (Test-Path -LiteralPath $envPath -PathType Leaf) {
        & git -C $repoRoot check-ignore -q -- .env
        if ($LASTEXITCODE -ne 0) {
            Add-Failure '.env exists but is not ignored by Git. Never commit local credentials.'
        }
    }

    $secretScriptPath = Join-Path $repoRoot 'scripts/check-secrets.ps1'
    if (Test-Path -LiteralPath $secretScriptPath -PathType Leaf) {
        $powerShellCommand = Get-Command pwsh -ErrorAction SilentlyContinue
        if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue }
        if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell -ErrorAction SilentlyContinue }
        $secretExitCode = 0
        if ($null -eq $powerShellCommand) {
            Add-Failure 'A PowerShell host is required to run scripts/check-secrets.ps1.'
        } else {
            & $powerShellCommand.Source -NoProfile -ExecutionPolicy Bypass -File $secretScriptPath | Out-Null
            $secretExitCode = $LASTEXITCODE
        }
        if ($secretExitCode -ne 0) {
            Add-Failure 'scripts/check-secrets.ps1 found a tracked credential or private-key pattern. Inspect the reported paths without printing secret contents.'
        }
    }

    $tokens = $null
    $parseErrors = $null
    $scriptPath = Join-Path $repoRoot 'scripts/verify-harness.ps1'
    if (Test-Path -LiteralPath $scriptPath -PathType Leaf) {
        [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count -gt 0) {
            Add-Failure 'scripts/verify-harness.ps1 has PowerShell parse errors. Fix the verifier before relying on its result.'
        }
    }
}

if ($Area -in @('All', 'Instructions')) {
    Test-Instructions
}
if ($Area -in @('All', 'State')) {
    Test-State
}
if ($Area -in @('All', 'Verification')) {
    Test-Verification
}

if ($failures.Count -gt 0) {
    Write-Output "HARNESS FAILED: area=$Area"
    foreach ($failure in $failures) {
        Write-Output "ERROR: $failure"
    }
    exit 1
}

Write-Output "HARNESS PASS: area=$Area"
exit 0
