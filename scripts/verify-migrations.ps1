[CmdletBinding()]
param(
    [switch]$StaticOnly,
    [string]$ProjectName = "ai-ops-platform-mvp",
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "docker-compose.yml"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$versionsPath = Join-Path $repoRoot "backend\migrations\versions"
$policyPath = Join-Path $repoRoot "deploy\migrations-policy.json"

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Migration policy failed: $Message" }
}

function Get-MigrationNodes {
    $files = @(Get-ChildItem -LiteralPath $versionsPath -Filter "*.py" -File | Sort-Object Name)
    Assert-Condition ($files.Count -gt 0) "no Alembic migration files were found"
    $nodes = foreach ($file in $files) {
        $content = Get-Content -Raw -LiteralPath $file.FullName
        $revision = [regex]::Match($content, '(?m)^revision\s*=\s*["'']([^"'']+)["'']').Groups[1].Value
        $downRevision = [regex]::Match($content, '(?m)^down_revision\s*=\s*(?:["'']([^"'']+)["'']|None)').Groups[1].Value
        Assert-Condition (-not [string]::IsNullOrWhiteSpace($revision)) "$($file.Name) has no revision identifier"
        [pscustomobject]@{ File = $file.Name; Revision = $revision; DownRevision = $downRevision }
    }
    return $nodes
}

function Test-StaticPolicy {
    foreach ($path in @($versionsPath, $policyPath, (Join-Path $repoRoot "docs\MIGRATIONS.md"))) {
        Assert-Condition (Test-Path -LiteralPath $path) "required migration policy path is missing: $path"
    }
    $policy = Get-Content -Raw -LiteralPath $policyPath | ConvertFrom-Json
    Assert-Condition ($policy.policy_version -eq "migrations.v1") "migration policy version drifted"
    Assert-Condition ($policy.mode -eq "forward_only") "production migration mode is not forward_only"
    Assert-Condition (-not [bool]$policy.production_downgrade_allowed) "production downgrade must remain disabled"

    $nodes = @(Get-MigrationNodes)
    $duplicateRevisions = @($nodes | Group-Object Revision | Where-Object Count -gt 1)
    Assert-Condition ($duplicateRevisions.Count -eq 0) "duplicate Alembic revision identifiers exist"
    $referenced = @($nodes | Where-Object { -not [string]::IsNullOrWhiteSpace($_.DownRevision) } | ForEach-Object DownRevision)
    $heads = @($nodes | Where-Object { $_.Revision -notin $referenced })
    Assert-Condition ($heads.Count -eq 1) "expected one linear migration head, found $($heads.Count)"
    Assert-Condition ($heads[0].Revision -eq [string]$policy.expected_head) "migration head is '$($heads[0].Revision)', expected '$($policy.expected_head)'"
    $baseNodes = @($nodes | Where-Object { [string]::IsNullOrWhiteSpace($_.DownRevision) })
    Assert-Condition ($baseNodes.Count -eq 1) "expected one base migration, found $($baseNodes.Count)"

    $migrationDocs = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "docs\MIGRATIONS.md")
    foreach ($marker in @("forward-only", "expand/contract", "alembic downgrade", "verify-migrations.ps1")) {
        Assert-Condition ($migrationDocs -match [regex]::Escape($marker)) "docs/MIGRATIONS.md is missing '$marker'"
    }
    return $policy
}

function Invoke-Compose {
    param([string[]]$Arguments)
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $docker) { $docker = Get-Command docker -ErrorAction SilentlyContinue }
    Assert-Condition ($null -ne $docker) "Docker CLI is required for the runtime migration check"
    $prefix = @("compose", "--project-name", $ProjectName, "--env-file", (Join-Path $repoRoot $EnvFile), "--file", (Join-Path $repoRoot $ComposeFile))
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $docker.Source @prefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "Compose migration command failed; output was withheld to avoid configuration disclosure" }
    return $output
}

try {
    $policy = Test-StaticPolicy
    if ($StaticOnly) {
        Write-Output "MIGRATION STATIC PASS: one linear head, forward-only manifest, expand/contract policy, and migration documentation verified."
        exit 0
    }
    Assert-Condition (Test-Path -LiteralPath (Join-Path $repoRoot $EnvFile)) "runtime env file is missing"
    $current = (Invoke-Compose -Arguments @("exec", "-T", "backend", "alembic", "current")) -join " "
    $heads = (Invoke-Compose -Arguments @("exec", "-T", "backend", "alembic", "heads")) -join " "
    Assert-Condition ($current -match [regex]::Escape([string]$policy.expected_head)) "database current revision does not match the expected head"
    Assert-Condition ($heads -match [regex]::Escape([string]$policy.expected_head)) "Alembic reported an unexpected head"
    Write-Output "MIGRATION RUNTIME PASS: database and migration runner are at $($policy.expected_head)."
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
