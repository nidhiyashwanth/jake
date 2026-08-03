[CmdletBinding()]
param(
    [ValidateRange(1, 512)]
    [int]$MaxGb = 32
)

$ErrorActionPreference = "Stop"

function Resolve-DockerExecutable {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $knownPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $knownPath) {
        return $knownPath
    }

    throw "Docker executable was not found. Start Docker Desktop or refresh PATH, then rerun this check."
}

function Convert-DockerSizeToBytes {
    param([Parameter(Mandatory)][string]$Value)

    if ($Value -notmatch "^\s*(?<number>[0-9]+(?:\.[0-9]+)?)\s*(?<unit>B|KB|MB|GB|TB)\s*$") {
        throw "Docker returned an unrecognized size '$Value'. Check 'docker system df' manually and update the parser."
    }

    $multipliers = @{
        B  = 1
        KB = 1KB
        MB = 1MB
        GB = 1GB
        TB = 1TB
    }
    return [double]$matches.number * [double]$multipliers[$matches.unit.ToUpperInvariant()]
}

$dockerExe = Resolve-DockerExecutable
$rows = @(& $dockerExe system df --format '{{json .}}' 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Docker storage inspection failed. Run '$dockerExe system df' and ensure the engine is running. Output: $($rows -join ' ')"
}

$totalBytes = 0.0
$parts = @()
foreach ($row in $rows) {
    if ([string]::IsNullOrWhiteSpace($row)) {
        continue
    }
    try {
        $item = $row | ConvertFrom-Json
    } catch {
        throw "Docker storage inspection returned invalid JSON: $row"
    }
    $bytes = Convert-DockerSizeToBytes -Value ([string]$item.Size)
    $totalBytes += $bytes
    $parts += "{0}={1}" -f $item.Type, $item.Size
}

$limitBytes = [double]$MaxGb * 1GB
$totalGb = $totalBytes / 1GB
Write-Output ("Docker usage: {0:N2} GB / {1:N2} GB ({2})" -f $totalGb, $MaxGb, ($parts -join ", "))

if ($totalBytes -gt $limitBytes) {
    throw ("Docker storage budget exceeded: {0:N2} GB is above the configured {1:N2} GB limit. " +
        "Remove only identified project images/cache/volumes; do not run a broad volume prune while data matters.") -f $totalGb, $MaxGb
}
