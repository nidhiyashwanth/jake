[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

function Require-Text {
    param([string]$RelativePath, [string]$Text)
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw ('Fresh-session check failed: missing ' + $RelativePath)
    }
    $content = Get-Content -Raw -LiteralPath $path
    if ($content.IndexOf($Text, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw ('Fresh-session check failed: ' + $RelativePath + ' does not route the required text')
    }
}

Require-Text -RelativePath 'AGENTS.md' -Text 'task.md'
Require-Text -RelativePath 'AGENTS.md' -Text 'scripts/verify-harness.ps1'
Require-Text -RelativePath 'AGENTS.md' -Text 'scripts/verify-product.ps1'
Require-Text -RelativePath 'task.md' -Text '## Master execution prompt'
Require-Text -RelativePath 'task.md' -Text '## Work package board'
Require-Text -RelativePath 'PROGRESS.md' -Text 'feature-list.json'
Require-Text -RelativePath 'DECISIONS.md' -Text 'D-007'

$features = Get-Content -Raw -LiteralPath (Join-Path $repoRoot 'feature-list.json') | ConvertFrom-Json
$active = @($features.features | Where-Object { $_.state -eq 'active' })
if ($active.Count -ne 1) {
    throw ('Fresh-session check failed: expected exactly one active package, found ' + $active.Count)
}

$taskContent = Get-Content -Raw -LiteralPath (Join-Path $repoRoot 'task.md')
$activeId = [regex]::Escape([string]$active[0].id)
$taskPattern = '(?m)^\|\s*{0}\s*\|.*\|\s*active\s*\|' -f $activeId
if ($taskContent -notmatch $taskPattern) {
    throw ('Fresh-session check failed: active package is not aligned in task.md')
}

& git -C $repoRoot check-ignore -q -- .env
if ($LASTEXITCODE -ne 0) {
    throw 'Fresh-session check failed: .env is not ignored'
}

Write-Output 'FRESH SESSION PASS: run, verify, state, decisions, task plan, and secret boundary are discoverable from repository files.'
exit 0
