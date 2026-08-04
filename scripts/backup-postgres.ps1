[CmdletBinding()]
param(
    [string]$ProjectName = "ai-ops-platform-mvp",
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "docker-compose.yml",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backupRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "artifacts\backups"))
$resolvedEnv = [IO.Path]::GetFullPath((Join-Path $repoRoot $EnvFile))
$resolvedCompose = [IO.Path]::GetFullPath((Join-Path $repoRoot $ComposeFile))

function Invoke-Compose {
    param([string[]]$Arguments)
    $prefix = @("compose", "--project-name", $ProjectName, "--env-file", $resolvedEnv, "--file", $resolvedCompose)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $script:docker.Source @prefix @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "PostgreSQL backup Compose command failed; configuration output was withheld" }
    return $output
}

if (-not (Test-Path -LiteralPath $resolvedEnv -PathType Leaf)) { throw "The ignored runtime env file is required and was not found" }
if (-not (Test-Path -LiteralPath $resolvedCompose -PathType Leaf)) { throw "Compose file was not found" }
$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $docker) { $docker = Get-Command docker -ErrorAction SilentlyContinue }
if ($null -eq $docker) { throw "Docker CLI is required for a PostgreSQL backup" }
$script:docker = $docker

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
    $OutputPath = Join-Path $backupRoot "postgres-$stamp.dump"
}
$resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
if (-not $resolvedOutput.StartsWith($backupRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup output must remain inside artifacts/backups"
}
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

$containerLines = @(Invoke-Compose -Arguments @("ps", "-q", "postgres"))
$container = (($containerLines | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -First 1) -as [string]).Trim()
if ([string]::IsNullOrWhiteSpace($container)) { throw "The named Compose project has no running PostgreSQL container" }

$remoteDump = "/tmp/ai-ops-postgres-$([guid]::NewGuid().ToString('N')).dump"
$currentOutput = @()
try {
    $dumpCommand = 'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "' + $remoteDump + '"'
    $null = Invoke-Compose -Arguments @("exec", "-T", "postgres", "sh", "-c", $dumpCommand)
    $copyOutput = @(& $script:docker.Source "cp" "$container`:$remoteDump" "$resolvedOutput" 2>&1)
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $resolvedOutput -PathType Leaf)) { throw "Docker could not copy the PostgreSQL backup into the workspace artifact directory" }
    $currentOutput = @(Invoke-Compose -Arguments @("exec", "-T", "backend", "alembic", "current"))
} finally {
    $null = Invoke-Compose -Arguments @("exec", "-T", "postgres", "rm", "-f", $remoteDump)
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedOutput).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    manifest_version = "postgres-backup.v1"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    sha256 = $hash
    format = "postgresql-custom"
    project = $ProjectName
    schema_head = (($currentOutput -join " ").Trim())
    source_database = "postgresql"
}
$manifestPath = "$resolvedOutput.json"
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output "POSTGRES BACKUP PASS: custom-format backup and SHA-256 manifest created under artifacts/backups ($hash)."
