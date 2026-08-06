[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupPath,
    [string]$ProjectName = "ai-ops-platform-mvp",
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "docker-compose.yml",
    [switch]$KeepDatabase
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = [IO.Path]::GetFullPath((Join-Path $repoRoot $EnvFile))
$resolvedCompose = [IO.Path]::GetFullPath((Join-Path $repoRoot $ComposeFile))
$resolvedBackup = [IO.Path]::GetFullPath($BackupPath)

function Invoke-Compose {
    param([string[]]$Arguments)
    $prefix = @("compose", "--project-name", $ProjectName, "--env-file", $resolvedEnv, "--file", $resolvedCompose)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $script:docker.Source @prefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "PostgreSQL restore Compose command failed; database output was withheld" }
    return $output
}

if (-not (Test-Path -LiteralPath $resolvedEnv -PathType Leaf)) { throw "The ignored runtime env file is required and was not found" }
if (-not (Test-Path -LiteralPath $resolvedCompose -PathType Leaf)) { throw "Compose file was not found" }
if (-not (Test-Path -LiteralPath $resolvedBackup -PathType Leaf)) { throw "Backup file was not found" }
$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $docker) { $docker = Get-Command docker -ErrorAction SilentlyContinue }
if ($null -eq $docker) { throw "Docker CLI is required for a PostgreSQL restore drill" }
$script:docker = $docker

$manifestPath = "$resolvedBackup.json"
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedBackup).Hash.ToLowerInvariant()
    if ($actualHash -ne [string]$manifest.sha256) { throw "Backup SHA-256 does not match its manifest" }
}

$containerLines = @(Invoke-Compose -Arguments @("ps", "-q", "postgres"))
$container = (($containerLines | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -First 1) -as [string]).Trim()
if ([string]::IsNullOrWhiteSpace($container)) { throw "The named Compose project has no running PostgreSQL container" }

$remoteDump = "/tmp/ai-ops-restore-$([guid]::NewGuid().ToString('N')).dump"
$restoreDatabase = "restore_drill_$([guid]::NewGuid().ToString('N').Substring(0, 16))"
$databaseCreated = $false
try {
    $copyOutput = @(& $script:docker.Source "cp" "$resolvedBackup" "$container`:$remoteDump" 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Docker could not copy the PostgreSQL backup into the isolated restore workspace" }
    $createCommand = 'createdb -U "$POSTGRES_USER" -T template0 "' + $restoreDatabase + '"'
    $null = Invoke-Compose -Arguments @("exec", "-T", "postgres", "sh", "-c", $createCommand)
    $databaseCreated = $true
    $restoreCommand = 'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "' + $restoreDatabase + '" "' + $remoteDump + '"'
    $null = Invoke-Compose -Arguments @("exec", "-T", "postgres", "sh", "-c", $restoreCommand)
    $query = "psql -At -v ON_ERROR_STOP=1 -U `"`$POSTGRES_USER`" -d `"$restoreDatabase`" -c 'SELECT (SELECT count(*) FROM alembic_version), (SELECT count(*) FROM workspaces);'"
    $checkOutput = (Invoke-Compose -Arguments @("exec", "-T", "postgres", "sh", "-c", $query)) -join "`n"
    $row = ($checkOutput -split "`n" | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -match '^[0-9]+\|[0-9]+$' } | Select-Object -Last 1)
    if ([string]::IsNullOrWhiteSpace($row)) { throw "Restore drill query returned no durable-schema row" }
    $parts = $row -split "\|"
    if ([int]$parts[0] -ne 1) { throw "Restored database does not contain exactly one Alembic head row" }
    Write-Output "POSTGRES RESTORE PASS: backup restored into an isolated temporary database and durable schema evidence verified."
} finally {
    if ($databaseCreated -and -not $KeepDatabase) {
        $dropCommand = 'dropdb -U "$POSTGRES_USER" "' + $restoreDatabase + '"'
        $null = Invoke-Compose -Arguments @("exec", "-T", "postgres", "sh", "-c", $dropCommand)
    }
    $null = Invoke-Compose -Arguments @("exec", "-T", "postgres", "rm", "-f", $remoteDump)
}
