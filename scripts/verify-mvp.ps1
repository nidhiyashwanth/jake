[CmdletBinding()]
param(
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"
$envTemplate = Join-Path $repoRoot ".env.example"
$fixture = Join-Path $repoRoot "tests\fixtures\coi-failing.txt"
$projectName = "ai-ops-platform-mvp"
$apiBaseUrl = "http://localhost:8000"
$started = $false
$tempFixture = $null

function Resolve-DockerExecutable {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) {
        $dockerBin = Split-Path -Parent $command.Source
        if (($env:Path -split ';') -notcontains $dockerBin) {
            $env:Path = "$dockerBin;$env:Path"
        }
        return $command.Source
    }

    $knownPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $knownPath) {
        $dockerBin = Split-Path -Parent $knownPath
        if (($env:Path -split ';') -notcontains $dockerBin) {
            $env:Path = "$dockerBin;$env:Path"
        }
        return $knownPath
    }

    throw "Docker executable was not found. Start Docker Desktop or refresh PATH, then rerun scripts\verify-mvp.ps1."
}

$dockerExe = Resolve-DockerExecutable
$composePrefix = @(
    "compose",
    "--project-name", $projectName,
    "--env-file", $envFile,
    "--file", $composeFile
)

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $dockerExe @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker command failed: $dockerExe $($Arguments -join ' ')`n$($output -join "`n")"
    }
    return $output
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    return Invoke-Docker -Arguments ($composePrefix + $Arguments)
}

function Get-HttpErrorDetail {
    param([Parameter(Mandatory)]$Exception)

    $response = $Exception.Response
    if ($null -eq $response) {
        return $Exception.Message
    }
    try {
        $status = [int]$response.StatusCode
        $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
        try {
            $body = $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
        return "HTTP ${status}: $body"
    } catch {
        return $Exception.Message
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [int]$Attempts = 60
    )

    $lastError = "no response"
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                Write-Output "Ready: GET $Uri"
                return
            }
            $lastError = "HTTP $($response.StatusCode)"
        } catch {
            $lastError = Get-HttpErrorDetail -Exception $_.Exception
        }
        Start-Sleep -Seconds 2
    }
    throw "GET $Uri did not become ready after $Attempts attempts. Last error: $lastError. Repair: inspect 'docker compose logs backend postgres' and rerun after fixing the first failing service."
}

function Invoke-JsonApi {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "PATCH")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [AllowNull()][object]$Body = $null
    )

    $uri = "$apiBaseUrl$Path"
    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Uri $uri -Method $Method -UseBasicParsing -TimeoutSec 15
        }
        $json = $Body | ConvertTo-Json -Depth 20 -Compress
        return Invoke-RestMethod -Uri $uri -Method $Method -ContentType "application/json" -Body $json -UseBasicParsing -TimeoutSec 15
    } catch {
        $detail = Get-HttpErrorDetail -Exception $_.Exception
        throw "API $Method $Path failed. $detail Repair: compare the request with docs\MVP-CONTRACT.md and inspect backend logs before retrying."
    }
}

function Invoke-MultipartUpload {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$FilePath
    )

    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/plain")
        $form.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
        $form.Add([System.Net.Http.StringContent]::new("COI"), "doc_type")
        $response = $client.PostAsync("$apiBaseUrl$Path", $form).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "API POST $Path failed. HTTP $([int]$response.StatusCode): $body Repair: confirm the fixture is UTF-8 text and the backend accepts multipart file plus doc_type=COI."
        }
        return $body | ConvertFrom-Json
    } finally {
        $form.Dispose()
        $client.Dispose()
    }
}

function Assert-Condition {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Message
    )
    if (-not $Condition) {
        throw "Assertion failed: $Message Repair: inspect the last API response and the corresponding service logs."
    }
}

try {
    foreach ($requiredPath in @($composeFile, $envFile, $fixture)) {
        Assert-Condition -Condition (Test-Path -LiteralPath $requiredPath) -Message "Required verification file is missing: $requiredPath"
    }
    Assert-Condition -Condition (Test-Path -LiteralPath $envTemplate) -Message "The committed .env.example template is missing: $envTemplate"
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "frontend"))) {
        throw "E2E prerequisite missing: frontend\ is not present at $repoRoot\frontend. Integrate the Next.js review-desk slice before running the full Compose verifier."
    }

    Write-Output "Checking Docker storage budget before pulling or building images..."
    & (Join-Path $PSScriptRoot "check-docker-storage.ps1") -MaxGb 32
    if ($LASTEXITCODE -ne 0) {
        throw "Docker storage guard failed. Do not continue until usage is below 32 GB."
    }

    Write-Output "Validating Docker Compose syntax..."
    $null = Invoke-Compose -Arguments @("config", "--quiet")

    Write-Output "Starting PostgreSQL 16, FastAPI, and Next.js services..."
    $null = Invoke-Compose -Arguments @("up", "-d", "--build")
    $started = $true
    Wait-HttpReady -Uri "$apiBaseUrl/api/health"

    $runTag = [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
    $legalName = "Acme Mechanical $runTag LLC"
    $vendor = Invoke-JsonApi -Method POST -Path "/api/vendors" -Body @{ legal_name = $legalName }
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($vendor.id)) -Message "POST /api/vendors did not return a vendor id"

    $fixtureText = [System.IO.File]::ReadAllText($fixture)
    $fixtureText = $fixtureText.Replace("{{VENDOR_NAME}}", $legalName)
    $tempFixture = Join-Path ([System.IO.Path]::GetTempPath()) "ai-ops-coi-$runTag.txt"
    [System.IO.File]::WriteAllText($tempFixture, $fixtureText, [System.Text.UTF8Encoding]::new($false))
    $document = Invoke-MultipartUpload -Path "/api/vendors/$($vendor.id)/documents" -FilePath $tempFixture
    Assert-Condition -Condition (-not [string]::IsNullOrWhiteSpace($document.id)) -Message "COI upload did not return a document id"

    $firstVerification = Invoke-JsonApi -Method POST -Path "/api/documents/$($document.id)/verify"
    Assert-Condition -Condition ($firstVerification.status.status -eq "needs_review") -Message "Initial verification should produce needs_review for the intentionally blank certificate holder"
    Assert-Condition -Condition (@($firstVerification.status.failing_requirements) -contains "certificate_holder_match") -Message "Initial verification did not expose certificate_holder_match as a failing requirement"

    $openReviews = @((Invoke-JsonApi -Method GET -Path "/api/reviews").items | Where-Object { $_.vendor_id -eq $vendor.id -and $_.status -eq "open" })
    Assert-Condition -Condition ($openReviews.Count -ge 1) -Message "Initial verification did not create an open review task"
    $holderReview = $openReviews | Where-Object { $_.correction_field -eq "certificate_holder" } | Select-Object -First 1
    Assert-Condition -Condition ($null -ne $holderReview) -Message "No certificate_holder review task was available for human correction"

    $secondVerification = Invoke-JsonApi -Method PATCH -Path "/api/reviews/$($holderReview.id)" -Body @{ field = "certificate_holder"; value = "Northwind Construction LLC" }
    Assert-Condition -Condition ($secondVerification.status.status -eq "compliant") -Message "Review correction did not produce compliant status"

    $status = Invoke-JsonApi -Method GET -Path "/api/vendors/$($vendor.id)/status"
    $history = @($status.history)
    Assert-Condition -Condition ($history.Count -ge 2) -Message "Status endpoint returned fewer than two point-in-time snapshots"
    Assert-Condition -Condition ($history[0].id -ne $history[1].id) -Message "Historical status snapshots are not append-only distinct records"
    Assert-Condition -Condition ($history[0].status -eq "compliant" -and $history[1].status -eq "needs_review") -Message "Status history does not show needs_review followed by compliant"

    $ledger = Invoke-JsonApi -Method GET -Path "/api/vendors/$($vendor.id)/ledger"
    $ledgerEvents = @($ledger.items)
    Assert-Condition -Condition ($ledgerEvents.event_type -contains "document_uploaded") -Message "Audit ledger is missing document_uploaded"
    Assert-Condition -Condition (($ledgerEvents.event_type | Where-Object { $_ -eq "verification_completed" }).Count -ge 2) -Message "Audit ledger is missing both verification_completed events"
    Assert-Condition -Condition ($ledgerEvents.event_type -contains "review_correction_applied") -Message "Audit ledger is missing review_correction_applied"

    $detail = Invoke-JsonApi -Method GET -Path "/api/vendors/$($vendor.id)"
    Assert-Condition -Condition (@($detail.recent_events).Count -ge 4) -Message "Vendor detail did not expose the audit evidence"

    Write-Output "F01 E2E PASS: vendor=$($vendor.id), initial=needs_review, corrected=compliant, snapshots=$($history.Count), ledger_events=$($ledgerEvents.Count)"
} finally {
    if ($tempFixture -and (Test-Path -LiteralPath $tempFixture)) {
        Remove-Item -LiteralPath $tempFixture -Force
    }
    if ($started -and -not $KeepRunning) {
        try {
            $null = Invoke-Compose -Arguments @("down", "--remove-orphans")
            Write-Output "Compose services stopped; the named PostgreSQL volume was preserved."
        } catch {
            Write-Warning "Cleanup failed. Run 'docker compose --project-name $projectName --file $composeFile down --remove-orphans' after reviewing the original failure."
        }
    }
}
