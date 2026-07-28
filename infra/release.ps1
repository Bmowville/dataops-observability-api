#requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet("Build", "WhatIf", "Deploy")]
    [string]$Mode = "Build",

    [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,

    [ValidateRange(360, 3600)]
    [int]$MigrationTimeoutSeconds = 600,

    [ValidateRange(300, 3600)]
    [int]$DeploymentTimeoutSeconds = 1200,

    [ValidateRange(60, 600)]
    [int]$SmokeTimeoutSeconds = 180,

    [string]$DeploymentPrefix = "dataops-portfolio-$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))",

    [switch]$ConfirmDeployment
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$location = "eastus2"
$jobRuntimeLimitSeconds = 300
$mainTemplate = Join-Path $PSScriptRoot "main.bicep"
$parameterFile = Join-Path $PSScriptRoot "main.bicepparam"
$artifactDirectory = Join-Path $PSScriptRoot ".artifacts"
$previewManifestPath = Join-Path $artifactDirectory "what-if-manifest.json"
$previewOutputPath = Join-Path $artifactDirectory "what-if-output.json"
$deploymentCancellationTimeoutSeconds = 180
$jobStartAmbiguityTimeoutSeconds = 120
$migrationStopConfirmationTimeoutSeconds = 120

if ($MigrationTimeoutSeconds -le ($jobRuntimeLimitSeconds + 30)) {
    throw "MigrationTimeoutSeconds must exceed the 300-second job limit by at least 30 seconds."
}

$azureCliCandidates = @(
    @(
        (Get-Command az -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
)

if ($azureCliCandidates.Count -eq 0) {
    throw "Azure CLI was not found. Install Azure CLI before running this release workflow."
}

$script:AzureCli = $azureCliCandidates | Select-Object -First 1

function Protect-AzureCliDiagnostics {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    $redacted = $Text
    foreach ($secretVariable in @(
        "NEON_POOLED_DATABASE_URL",
        "NEON_DIRECT_DATABASE_URL",
        "DATAOPS_INGESTION_API_KEY"
    )) {
        $secretValue = [Environment]::GetEnvironmentVariable($secretVariable, "Process")
        if (-not [string]::IsNullOrEmpty($secretValue)) {
            $redacted = $redacted.Replace($secretValue, "[REDACTED]")
            $escapedSecretValue = [Uri]::EscapeDataString($secretValue)
            if ($escapedSecretValue -ne $secretValue) {
                $redacted = $redacted.Replace($escapedSecretValue, "[REDACTED]")
            }
            $jsonEncodedSecretValue = $secretValue | ConvertTo-Json -Compress
            if ($jsonEncodedSecretValue.Length -ge 2) {
                $redacted = $redacted.Replace(
                    $jsonEncodedSecretValue.Substring(1, $jsonEncodedSecretValue.Length - 2),
                    "[REDACTED]"
                )
            }
        }
    }

    return $redacted
}

function Invoke-AzureCli {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [ValidateRange(10, 7200)]
        [int]$TimeoutSeconds = 900
    )

    $operation = ($Arguments | Select-Object -First 2) -join " "
    $serializedArguments = ConvertTo-Json -InputObject @($Arguments) -Compress
    $encodedArguments = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($serializedArguments))
    $runnerSource = @'
$ErrorActionPreference = "Stop"
try {
    $cliPath = [Environment]::GetEnvironmentVariable("DATAOPS_RELEASE_AZURE_CLI_PATH", "Process")
    $encodedArguments = [Environment]::GetEnvironmentVariable("DATAOPS_RELEASE_AZURE_CLI_ARGUMENTS", "Process")
    $argumentsJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedArguments))
    $cliArguments = @($argumentsJson | ConvertFrom-Json)
    & $cliPath @cliArguments
    if ($null -eq $LASTEXITCODE) {
        exit 1
    }
    exit $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
'@
    $encodedRunner = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($runnerSource))
    $powerShellExecutable = Join-Path $PSHOME "pwsh.exe"
    if (-not (Test-Path -LiteralPath $powerShellExecutable)) {
        $powerShellExecutable = Join-Path $PSHOME "pwsh"
    }

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $powerShellExecutable
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $startInfo.ArgumentList.Add("-NoLogo")
    $startInfo.ArgumentList.Add("-NoProfile")
    $startInfo.ArgumentList.Add("-NonInteractive")
    $startInfo.ArgumentList.Add("-EncodedCommand")
    $startInfo.ArgumentList.Add($encodedRunner)
    $startInfo.Environment["DATAOPS_RELEASE_AZURE_CLI_PATH"] = $script:AzureCli
    $startInfo.Environment["DATAOPS_RELEASE_AZURE_CLI_ARGUMENTS"] = $encodedArguments
    $startInfo.Environment["AZURE_CORE_NO_COLOR"] = "true"

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $stdoutTask = $null
    $stderrTask = $null

    try {
        if (-not $process.Start()) {
            throw "Azure CLI operation '$operation' could not start."
        }

        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $killFailure = $null
            try {
                $process.Kill($true)
            }
            catch {
                $killFailure = $_.Exception.Message
            }

            $terminated = $process.WaitForExit(10000)
            $streamsClosed = [Threading.Tasks.Task]::WaitAll(
                [Threading.Tasks.Task[]]@($stdoutTask, $stderrTask),
                10000
            )
            if (-not $terminated -or -not $streamsClosed -or $null -ne $killFailure) {
                $detail = if ($null -ne $killFailure) { " Kill failure: $killFailure" } else { "" }
                throw "Azure CLI operation '$operation' exceeded its $TimeoutSeconds-second timeout, and process-tree termination could not be confirmed because the root process or redirected descendant handles remained open.$detail"
            }

            throw "Azure CLI operation '$operation' exceeded its $TimeoutSeconds-second timeout. Its process tree was terminated."
        }

        $streamsClosed = [Threading.Tasks.Task]::WaitAll(
            [Threading.Tasks.Task[]]@($stdoutTask, $stderrTask),
            10000
        )
        if (-not $streamsClosed) {
            throw "Azure CLI operation '$operation' exited, but redirected descendant handles remained open. Process-tree termination is unconfirmed."
        }

        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {
            $diagnostics = Protect-AzureCliDiagnostics -Text ((@(
                $stderr.Trim(),
                $stdout.Trim()
            ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join [Environment]::NewLine)
            throw "Azure CLI operation '$operation' failed with exit code $($process.ExitCode). $diagnostics"
        }

        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            Write-Warning (Protect-AzureCliDiagnostics -Text $stderr.Trim())
        }

        if ([string]::IsNullOrEmpty($stdout)) {
            return @()
        }

        return @($stdout -split "\r?\n" | Where-Object { $_ -ne "" })
    }
    finally {
        $process.Dispose()
    }
}

function Get-RequiredEnvironmentVariable {
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required process environment variable $Name is not set."
    }

    return $value
}

function Invoke-SyntheticParameterBuild {
    $syntheticValues = [ordered]@{
        NEON_POOLED_DATABASE_URL = "validation-pooled-url"
        NEON_DIRECT_DATABASE_URL = "validation-direct-url"
        DATAOPS_INGESTION_API_KEY = "validation-only-not-a-secret"
        AZURE_DEPLOY_API = "false"
    }
    $originalValues = @{}

    try {
        foreach ($entry in $syntheticValues.GetEnumerator()) {
            $originalValues[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, "Process")
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        }

        Invoke-AzureCli -Arguments @(
            "bicep", "build-params",
            "--file", $parameterFile,
            "--stdout"
        ) -TimeoutSeconds 120 | Out-Null
    }
    finally {
        foreach ($entry in $syntheticValues.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $originalValues[$entry.Key], "Process")
        }
    }
}

function Assert-DatabaseConnectionPair {
    param(
        [Parameter(Mandatory)]
        [string]$PooledUrl,

        [Parameter(Mandatory)]
        [string]$DirectUrl
    )

    try {
        $pooledUri = [Uri]$PooledUrl
        $directUri = [Uri]$DirectUrl
    }
    catch {
        throw "The Neon connection variables must contain valid URLs. Values were not printed."
    }

    if ($pooledUri.Scheme -notin @("postgres", "postgresql") -or $directUri.Scheme -notin @("postgres", "postgresql")) {
        throw "Both Neon connection variables must use a PostgreSQL URL scheme."
    }

    if ($pooledUri.Host -notlike "*.neon.tech" -or $directUri.Host -notlike "*.neon.tech") {
        throw "Both database hosts must be Neon-managed *.neon.tech endpoints."
    }

    if ($pooledUri.Host -notmatch "-pooler(?:\.|$)") {
        throw "NEON_POOLED_DATABASE_URL must use Neon's pooled hostname."
    }

    if ($directUri.Host -match "-pooler(?:\.|$)") {
        throw "NEON_DIRECT_DATABASE_URL must use Neon's direct, non-pooled hostname."
    }

    foreach ($uri in @($pooledUri, $directUri)) {
        if ($uri.Query -notmatch "(?i)(?:^|[?&])sslmode=require(?:&|$)") {
            throw "Both Neon URLs must include sslmode=require."
        }

        if ($uri.Query -notmatch "(?i)(?:^|[?&])channel_binding=require(?:&|$)") {
            throw "Both Neon URLs must preserve channel_binding=require."
        }

        $credentials = $uri.UserInfo -split ":", 2
        if (
            $credentials.Count -ne 2 -or
            [string]::IsNullOrWhiteSpace($credentials[0]) -or
            [string]::IsNullOrWhiteSpace($credentials[1]) -or
            [string]::IsNullOrWhiteSpace($uri.AbsolutePath.Trim("/"))
        ) {
            throw "Both Neon URLs must include a username, password, and database name."
        }
    }

    $normalizedPooledHost = $pooledUri.Host -replace "-pooler(?=\.)", ""
    $pooledCredentials = $pooledUri.UserInfo -split ":", 2
    $directCredentials = $directUri.UserInfo -split ":", 2
    $pooledPort = if ($pooledUri.Port -lt 0) { 5432 } else { $pooledUri.Port }
    $directPort = if ($directUri.Port -lt 0) { 5432 } else { $directUri.Port }

    if (
        $normalizedPooledHost -ine $directUri.Host -or
        $pooledUri.AbsolutePath -cne $directUri.AbsolutePath -or
        $pooledCredentials[0] -cne $directCredentials[0] -or
        $pooledPort -ne $directPort
    ) {
        throw "The pooled and direct Neon URLs must target the same project, branch, database, user, and port."
    }
}

function Get-IacFileFingerprints {
    $relativeFiles = @(
        "main.bicep",
        "main.bicepparam",
        "modules/api.bicep",
        "modules/container-apps-platform.bicep",
        "release.ps1"
    )

    return @(
        foreach ($relativeFile in $relativeFiles) {
            $absolutePath = Join-Path $PSScriptRoot $relativeFile
            [ordered]@{
                path = $relativeFile.Replace("\", "/")
                sha256 = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
}

function Get-DeploymentInputFingerprints {
    param(
        [Parameter(Mandatory)]
        [string]$Salt,

        [Parameter(Mandatory)]
        [string]$PooledDatabaseUrl,

        [Parameter(Mandatory)]
        [string]$DirectDatabaseUrl,

        [Parameter(Mandatory)]
        [string]$IngestionApiKey
    )

    try {
        $saltBytes = [Convert]::FromBase64String($Salt)
    }
    catch {
        throw "The what-if manifest contains an invalid fingerprint salt. Run -Mode WhatIf again."
    }

    if ($saltBytes.Length -ne 32) {
        throw "The what-if manifest contains an invalid fingerprint salt. Run -Mode WhatIf again."
    }

    $fingerprint = {
        param(
            [string]$Name,
            [string]$Value
        )

        $hmac = [Security.Cryptography.HMACSHA256]::new($saltBytes)
        try {
            $digest = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes("$Name`0$Value"))
            return ($digest | ForEach-Object { $_.ToString("x2") }) -join ""
        }
        finally {
            $hmac.Dispose()
        }
    }

    return [ordered]@{
        NEON_POOLED_DATABASE_URL = & $fingerprint "NEON_POOLED_DATABASE_URL" $PooledDatabaseUrl
        NEON_DIRECT_DATABASE_URL = & $fingerprint "NEON_DIRECT_DATABASE_URL" $DirectDatabaseUrl
        DATAOPS_INGESTION_API_KEY = & $fingerprint "DATAOPS_INGESTION_API_KEY" $IngestionApiKey
    }
}

function Save-WhatIfManifest {
    param(
        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [Parameter(Mandatory)]
        [string]$TargetDeploymentPrefix,

        [Parameter(Mandatory)]
        [string]$PooledDatabaseUrl,

        [Parameter(Mandatory)]
        [string]$DirectDatabaseUrl,

        [Parameter(Mandatory)]
        [string]$IngestionApiKey
    )

    New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
    if (-not (Test-Path -LiteralPath $previewOutputPath)) {
        throw "The FullResourcePayloads what-if output is missing; no approval manifest was saved."
    }

    $saltBytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($saltBytes)
    $fingerprintSalt = [Convert]::ToBase64String($saltBytes)
    $manifest = [ordered]@{
        version = 3
        subscriptionId = $TargetSubscriptionId
        deploymentPrefix = $TargetDeploymentPrefix
        location = $location
        deployApi = $true
        createdAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        secretFingerprintSalt = $fingerprintSalt
        deploymentInputFingerprints = Get-DeploymentInputFingerprints `
            -Salt $fingerprintSalt `
            -PooledDatabaseUrl $PooledDatabaseUrl `
            -DirectDatabaseUrl $DirectDatabaseUrl `
            -IngestionApiKey $IngestionApiKey
        whatIf = [ordered]@{
            file = Split-Path -Leaf $previewOutputPath
            resultFormat = "FullResourcePayloads"
            sha256 = (Get-FileHash -LiteralPath $previewOutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        files = Get-IacFileFingerprints
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $previewManifestPath -Encoding utf8
}

function Assert-CurrentWhatIfManifest {
    param(
        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [Parameter(Mandatory)]
        [string]$TargetDeploymentPrefix,

        [Parameter(Mandatory)]
        [string]$PooledDatabaseUrl,

        [Parameter(Mandatory)]
        [string]$DirectDatabaseUrl,

        [Parameter(Mandatory)]
        [string]$IngestionApiKey
    )

    if (-not (Test-Path -LiteralPath $previewManifestPath)) {
        throw "No what-if manifest exists. Run -Mode WhatIf, review it, and then retry the approved deployment."
    }

    try {
        $manifest = Get-Content -Raw -LiteralPath $previewManifestPath | ConvertFrom-Json
        if ($manifest.version -ne 3) {
            throw "unsupported manifest version"
        }
        $createdAt = [DateTimeOffset]::Parse($manifest.createdAtUtc, [Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        throw "The what-if manifest is invalid or obsolete. Run -Mode WhatIf again."
    }

    $age = [DateTimeOffset]::UtcNow - $createdAt

    if ($age.TotalHours -lt 0 -or $age.TotalHours -gt 24) {
        throw "The reviewed what-if manifest is older than 24 hours. Run -Mode WhatIf again."
    }

    if (
        $manifest.subscriptionId -ne $TargetSubscriptionId -or
        $manifest.deploymentPrefix -cne $TargetDeploymentPrefix -or
        $manifest.location -cne $location -or
        $manifest.deployApi -ne $true
    ) {
        throw "The reviewed what-if target no longer matches the requested deployment."
    }

    $currentInputFingerprints = Get-DeploymentInputFingerprints `
        -Salt $manifest.secretFingerprintSalt `
        -PooledDatabaseUrl $PooledDatabaseUrl `
        -DirectDatabaseUrl $DirectDatabaseUrl `
        -IngestionApiKey $IngestionApiKey
    foreach ($inputVariable in @(
        "NEON_POOLED_DATABASE_URL",
        "NEON_DIRECT_DATABASE_URL",
        "DATAOPS_INGESTION_API_KEY"
    )) {
        if ($manifest.deploymentInputFingerprints.$inputVariable -cne $currentInputFingerprints[$inputVariable]) {
            throw "A deployment input changed after what-if. Run -Mode WhatIf again."
        }
    }

    if (
        $manifest.whatIf.file -cne (Split-Path -Leaf $previewOutputPath) -or
        $manifest.whatIf.resultFormat -cne "FullResourcePayloads" -or
        -not (Test-Path -LiteralPath $previewOutputPath)
    ) {
        throw "The reviewed FullResourcePayloads what-if artifact is missing or invalid. Run -Mode WhatIf again."
    }

    $currentWhatIfHash = (Get-FileHash -LiteralPath $previewOutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifest.whatIf.sha256 -cne $currentWhatIfHash) {
        throw "The reviewed FullResourcePayloads what-if artifact changed after preview. Run -Mode WhatIf again."
    }

    foreach ($currentFile in Get-IacFileFingerprints) {
        $reviewedFile = @($manifest.files | Where-Object { $_.path -eq $currentFile.path })
        if ($reviewedFile.Count -ne 1 -or $reviewedFile[0].sha256 -ne $currentFile.sha256) {
            throw "Infrastructure file '$($currentFile.path)' changed after what-if. Run -Mode WhatIf again."
        }
    }
}

function Enter-ReleaseLock {
    param(
        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId
    )

    New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
    $lockPath = Join-Path $artifactDirectory "release.lock"
    $stream = $null

    try {
        $stream = [IO.File]::Open(
            $lockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch [IO.IOException] {
        throw "Another release process holds '$lockPath'. Do not retry until the prior release process has exited and its Azure deployment or migration is confirmed terminal."
    }

    try {
        $metadata = [ordered]@{
            processId = $PID
            subscriptionId = $TargetSubscriptionId
            acquiredAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        } | ConvertTo-Json
        $metadataBytes = [Text.Encoding]::UTF8.GetBytes($metadata)
        $stream.SetLength(0)
        $stream.Write($metadataBytes, 0, $metadataBytes.Length)
        $stream.Flush($true)
    }
    catch {
        $stream.Dispose()
        throw
    }

    return [pscustomobject]@{
        Path = $lockPath
        Stream = $stream
    }
}

function Save-ExecutionStatus {
    param(
        [Parameter(Mandatory)]
        [string]$ExecutionName,

        [Parameter(Mandatory)]
        [string]$Status,

        [string]$ResourceGroupName,

        [string]$JobName,

        [string]$TargetSubscriptionId,

        [bool]$TerminalStateConfirmed = $true
    )

    New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
    $statusRecord = [ordered]@{
        executionName = $ExecutionName
        status = $Status
        terminalStateConfirmed = $TerminalStateConfirmed
        resourceGroupName = $ResourceGroupName
        jobName = $JobName
        subscriptionId = $TargetSubscriptionId
        observedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
    }
    $statusPath = Join-Path $artifactDirectory "migration-execution-status.json"
    $statusRecord | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

function Get-SubscriptionDeploymentState {
    param(
        [Parameter(Mandatory)]
        [string]$DeploymentName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [ValidateRange(10, 120)]
        [int]$TimeoutSeconds = 30
    )

    return ((Invoke-AzureCli -Arguments @(
        "deployment", "sub", "show",
        "--name", $DeploymentName,
        "--subscription", $TargetSubscriptionId,
        "--query", "properties.provisioningState",
        "--output", "tsv"
    ) -TimeoutSeconds $TimeoutSeconds) -join "").Trim()
}

function Stop-SubscriptionDeploymentAndConfirm {
    param(
        [Parameter(Mandatory)]
        [string]$DeploymentName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [ValidateRange(30, 600)]
        [int]$TimeoutSeconds
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastState = "NotObserved"
    $wasObserved = $false
    $cancelRequested = $false
    $cancelFailure = $null
    $lastQueryFailure = $null
    do {
        $remainingSeconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalSeconds)
        if ($remainingSeconds -lt 10) {
            break
        }

        try {
            $lastState = Get-SubscriptionDeploymentState `
                -DeploymentName $DeploymentName `
                -TargetSubscriptionId $TargetSubscriptionId `
                -TimeoutSeconds ([Math]::Min(30, $remainingSeconds))
            $wasObserved = $true
            $lastQueryFailure = $null
            if ($lastState -in @("Succeeded", "Failed", "Canceled")) {
                return [pscustomobject]@{
                    Confirmed = $true
                    WasObserved = $true
                    State = $lastState
                    CancelRequested = $cancelRequested
                    CancelFailure = $cancelFailure
                    QueryFailure = $null
                }
            }
        }
        catch {
            $lastQueryFailure = $_.Exception.Message
        }

        if (-not $cancelRequested) {
            $remainingSeconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalSeconds)
            if ($remainingSeconds -ge 10) {
                try {
                    Invoke-AzureCli -Arguments @(
                        "deployment", "sub", "cancel",
                        "--name", $DeploymentName,
                        "--subscription", $TargetSubscriptionId,
                        "--output", "none"
                    ) -TimeoutSeconds ([Math]::Min(30, $remainingSeconds)) | Out-Null
                    $cancelRequested = $true
                    $cancelFailure = $null
                }
                catch {
                    $cancelFailure = $_.Exception.Message
                }
            }
        }

        $remainingSeconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalSeconds)
        if ($remainingSeconds -gt 0) {
            Start-Sleep -Seconds ([Math]::Min(5, $remainingSeconds))
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    return [pscustomobject]@{
        Confirmed = $false
        WasObserved = $wasObserved
        State = $lastState
        CancelRequested = $cancelRequested
        CancelFailure = $cancelFailure
        QueryFailure = $lastQueryFailure
    }
}

function Invoke-SubscriptionDeployment {
    param(
        [Parameter(Mandatory)]
        [string]$DeploymentName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId
    )

    try {
        Invoke-AzureCli -Arguments @(
            "deployment", "sub", "create",
            "--name", $DeploymentName,
            "--location", $location,
            "--parameters", $parameterFile,
            "--subscription", $TargetSubscriptionId,
            "--no-prompt", "true",
            "--no-wait",
            "--output", "none"
        ) -TimeoutSeconds 120 | Out-Null

        Invoke-AzureCli -Arguments @(
            "deployment", "sub", "wait",
            "--name", $DeploymentName,
            "--subscription", $TargetSubscriptionId,
            "--custom", "properties.provisioningState=='Succeeded' || properties.provisioningState=='Failed' || properties.provisioningState=='Canceled'",
            "--interval", "10",
            "--timeout", [string]$DeploymentTimeoutSeconds,
            "--output", "none"
        ) -TimeoutSeconds ($DeploymentTimeoutSeconds + 30) | Out-Null

        $state = Get-SubscriptionDeploymentState `
            -DeploymentName $DeploymentName `
            -TargetSubscriptionId $TargetSubscriptionId `
            -TimeoutSeconds 120

        if ($state -ne "Succeeded") {
            throw "Subscription deployment '$DeploymentName' ended with state '$state'."
        }
    }
    catch {
        $originalFailure = $_
        try {
            $outcome = Stop-SubscriptionDeploymentAndConfirm `
                -DeploymentName $DeploymentName `
                -TargetSubscriptionId $TargetSubscriptionId `
                -TimeoutSeconds $deploymentCancellationTimeoutSeconds
        }
        catch {
            $outcome = [pscustomobject]@{
                Confirmed = $false
                WasObserved = $false
                State = "Unknown"
                CancelRequested = $false
                CancelFailure = "Cancellation helper failed: $($_.Exception.Message)"
                QueryFailure = $null
            }
        }

        $message = "Subscription deployment '$DeploymentName' submission, wait, or terminal-state verification failed; Azure acceptance may have occurred. Original error: $($originalFailure.Exception.Message)"
        if ($outcome.Confirmed) {
            $message += " Reconciliation confirmed exact-name terminal state '$($outcome.State)'."
        }
        elseif (-not $outcome.WasObserved) {
            $message += " The exact deployment name could not be found during bounded reconciliation, so acceptance and cancellation are UNCONFIRMED."
        }
        else {
            $message += " The exact deployment remained in nonterminal state '$($outcome.State)', so cancellation is UNCONFIRMED."
        }
        if ($null -ne $outcome.CancelFailure) {
            $message += " Last cancellation error: $($outcome.CancelFailure)"
        }
        if ($null -ne $outcome.QueryFailure) {
            $message += " Last exact-name query error: $($outcome.QueryFailure)"
        }
        if (-not $outcome.Confirmed) {
            $message += " Do not retry until the exact deployment name '$DeploymentName' has been checked and reports Succeeded, Failed, or Canceled, or its absence is independently confirmed after Azure propagation."
        }

        throw [InvalidOperationException]::new($message, $originalFailure.Exception)
    }
}

function Get-DeploymentOutput {
    param(
        [Parameter(Mandatory)]
        [string]$DeploymentName,

        [Parameter(Mandatory)]
        [string]$OutputName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId
    )

    $value = ((Invoke-AzureCli -Arguments @(
        "deployment", "sub", "show",
        "--name", $DeploymentName,
        "--subscription", $TargetSubscriptionId,
        "--query", "properties.outputs.$OutputName.value",
        "--output", "tsv"
    ) -TimeoutSeconds 120) -join "").Trim()

    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Deployment '$DeploymentName' did not return output '$OutputName'."
    }

    return $value
}

function Get-MigrationExecutionRecords {
    param(
        [Parameter(Mandatory)]
        [string]$ResourceGroupName,

        [Parameter(Mandatory)]
        [string]$JobName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [ValidateRange(10, 120)]
        [int]$TimeoutSeconds = 120
    )

    $executionJson = (Invoke-AzureCli -Arguments @(
        "containerapp", "job", "execution", "list",
        "--name", $JobName,
        "--resource-group", $ResourceGroupName,
        "--subscription", $TargetSubscriptionId,
        "--query", "[].{name:name,status:properties.status,startTime:properties.startTime,endTime:properties.endTime}",
        "--output", "json"
    ) -TimeoutSeconds $TimeoutSeconds) -join [Environment]::NewLine

    try {
        $executions = @($executionJson | ConvertFrom-Json)
    }
    catch {
        throw "Azure returned invalid JSON while listing migration executions."
    }

    return @($executions | ForEach-Object {
        [pscustomobject]@{
            Name = [string]$_.name
            Status = [string]$_.status
            StartTime = [string]$_.startTime
            EndTime = [string]$_.endTime
        }
    })
}

function Get-ActiveMigrationExecutionNames {
    param(
        [Parameter(Mandatory)]
        [string]$ResourceGroupName,

        [Parameter(Mandatory)]
        [string]$JobName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId
    )

    return @(
        Get-MigrationExecutionRecords `
            -ResourceGroupName $ResourceGroupName `
            -JobName $JobName `
            -TargetSubscriptionId $TargetSubscriptionId |
            Where-Object { [string]::IsNullOrWhiteSpace($_.EndTime) } |
            ForEach-Object { $_.Name } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
}

function Get-MigrationExecutionObservation {
    param(
        [Parameter(Mandatory)]
        [string]$ResourceGroupName,

        [Parameter(Mandatory)]
        [string]$JobName,

        [Parameter(Mandatory)]
        [string]$ExecutionName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [ValidateRange(10, 120)]
        [int]$TimeoutSeconds = 60
    )

    $observationJson = (Invoke-AzureCli -Arguments @(
        "containerapp", "job", "execution", "show",
        "--name", $JobName,
        "--resource-group", $ResourceGroupName,
        "--job-execution-name", $ExecutionName,
        "--subscription", $TargetSubscriptionId,
        "--query", "{status:properties.status,endTime:properties.endTime}",
        "--output", "json"
    ) -TimeoutSeconds $TimeoutSeconds) -join [Environment]::NewLine

    try {
        $observation = $observationJson | ConvertFrom-Json
    }
    catch {
        throw "Azure returned invalid JSON for migration execution '$ExecutionName'."
    }

    return [pscustomobject]@{
        Status = [string]$observation.status
        EndTime = [string]$observation.endTime
    }
}

function Stop-MigrationExecutionAndConfirm {
    param(
        [Parameter(Mandatory)]
        [string]$ResourceGroupName,

        [Parameter(Mandatory)]
        [string]$JobName,

        [Parameter(Mandatory)]
        [string]$ExecutionName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId
    )

    $stopRequestFailure = $null
    try {
        Invoke-AzureCli -Arguments @(
            "containerapp", "job", "stop",
            "--name", $JobName,
            "--resource-group", $ResourceGroupName,
            "--job-execution-name", $ExecutionName,
            "--subscription", $TargetSubscriptionId,
            "--no-wait",
            "--output", "none"
        ) -TimeoutSeconds 120 | Out-Null
    }
    catch {
        $stopRequestFailure = $_.Exception.Message
    }

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($migrationStopConfirmationTimeoutSeconds)
    $status = "Unknown"
    $endTime = $null
    $lastQueryFailure = $null
    do {
        try {
            $observation = Get-MigrationExecutionObservation `
                -ResourceGroupName $ResourceGroupName `
                -JobName $JobName `
                -ExecutionName $ExecutionName `
                -TargetSubscriptionId $TargetSubscriptionId `
                -TimeoutSeconds 30
            $status = $observation.Status
            $endTime = $observation.EndTime
            $lastQueryFailure = $null
            if (-not [string]::IsNullOrWhiteSpace($endTime)) {
                return [pscustomobject]@{
                    Confirmed = $true
                    Status = $status
                    EndTime = $endTime
                    StopRequestFailure = $stopRequestFailure
                    LastQueryFailure = $null
                }
            }
        }
        catch {
            $lastQueryFailure = $_.Exception.Message
        }

        Start-Sleep -Seconds 5
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    return [pscustomobject]@{
        Confirmed = $false
        Status = $status
        EndTime = $endTime
        StopRequestFailure = $stopRequestFailure
        LastQueryFailure = $lastQueryFailure
    }
}

function Resolve-AmbiguousMigrationStart {
    param(
        [Parameter(Mandatory)]
        [string]$ResourceGroupName,

        [Parameter(Mandatory)]
        [string]$JobName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId,

        [Parameter(Mandatory)]
        [DateTimeOffset]$AttemptedAtUtc,

        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [string[]]$KnownExecutionNames
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($jobStartAmbiguityTimeoutSeconds)
    $discoveredCandidateNames = @()
    $lastNonterminalNames = @()
    $lastQueryFailure = $null

    do {
        $remainingSeconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalSeconds)
        if ($remainingSeconds -lt 10) {
            break
        }

        try {
            $records = @(Get-MigrationExecutionRecords `
                -ResourceGroupName $ResourceGroupName `
                -JobName $JobName `
                -TargetSubscriptionId $TargetSubscriptionId `
                -TimeoutSeconds ([Math]::Min(30, $remainingSeconds)))
            $lastQueryFailure = $null
            $lastNonterminalNames = @(
                $records |
                    Where-Object { [string]::IsNullOrWhiteSpace($_.EndTime) } |
                    ForEach-Object { $_.Name } |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
            )

            foreach ($record in $records) {
                if (
                    [string]::IsNullOrWhiteSpace($record.Name) -or
                    $KnownExecutionNames -ccontains $record.Name
                ) {
                    continue
                }

                $appearedAfterAttempt = $true
                if (-not [string]::IsNullOrWhiteSpace($record.StartTime)) {
                    $parsedStartTime = [DateTimeOffset]::MinValue
                    if ([DateTimeOffset]::TryParse($record.StartTime, [ref]$parsedStartTime)) {
                        # Azure timestamps can lag the local clock slightly. The pre-start
                        # execution-name snapshot remains the primary attribution boundary.
                        $appearedAfterAttempt = $parsedStartTime -ge $AttemptedAtUtc.AddMinutes(-2)
                    }
                }

                if ($appearedAfterAttempt -and $discoveredCandidateNames -cnotcontains $record.Name) {
                    $discoveredCandidateNames += $record.Name
                }
            }

            $activeCandidateNames = @(
                $lastNonterminalNames | Where-Object { $discoveredCandidateNames -ccontains $_ }
            )
            if ($activeCandidateNames.Count -eq 1 -and $lastNonterminalNames.Count -eq 1) {
                $exactExecutionName = $activeCandidateNames[0]
                try {
                    $stopResult = Stop-MigrationExecutionAndConfirm `
                        -ResourceGroupName $ResourceGroupName `
                        -JobName $JobName `
                        -ExecutionName $exactExecutionName `
                        -TargetSubscriptionId $TargetSubscriptionId
                }
                catch {
                    $stopResult = [pscustomobject]@{
                        Confirmed = $false
                        Status = "Unknown"
                        EndTime = $null
                        StopRequestFailure = "Stop-confirmation helper failed: $($_.Exception.Message)"
                        LastQueryFailure = $null
                    }
                }

                return [pscustomobject]@{
                    ExactExecutionName = $exactExecutionName
                    ExactStopAttempted = $true
                    StopConfirmed = $stopResult.Confirmed
                    StopStatus = $stopResult.Status
                    StopEndTime = $stopResult.EndTime
                    StopRequestFailure = $stopResult.StopRequestFailure
                    DiscoveredCandidates = @($discoveredCandidateNames)
                    NonterminalExecutions = if ($stopResult.Confirmed) { @() } else { @($lastNonterminalNames) }
                    QueryFailure = $stopResult.LastQueryFailure
                }
            }

            $activeCandidateNames = @(
                $lastNonterminalNames | Where-Object { $discoveredCandidateNames -ccontains $_ }
            )
            if ($discoveredCandidateNames.Count -gt 0 -and $activeCandidateNames.Count -eq 0 -and $lastNonterminalNames.Count -eq 0) {
                return [pscustomobject]@{
                    ExactExecutionName = $null
                    ExactStopAttempted = $false
                    StopConfirmed = $false
                    StopStatus = $null
                    StopEndTime = $null
                    StopRequestFailure = $null
                    DiscoveredCandidates = @($discoveredCandidateNames)
                    NonterminalExecutions = @()
                    QueryFailure = $null
                }
            }
        }
        catch {
            $lastQueryFailure = $_.Exception.Message
        }

        $remainingSeconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalSeconds)
        if ($remainingSeconds -gt 0) {
            Start-Sleep -Seconds ([Math]::Min(5, $remainingSeconds))
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    return [pscustomobject]@{
        ExactExecutionName = $null
        ExactStopAttempted = $false
        StopConfirmed = $false
        StopStatus = $null
        StopEndTime = $null
        StopRequestFailure = $null
        DiscoveredCandidates = @($discoveredCandidateNames)
        NonterminalExecutions = @($lastNonterminalNames)
        QueryFailure = $lastQueryFailure
    }
}

function Save-MigrationStartAmbiguity {
    param(
        [Parameter(Mandatory)]
        [DateTimeOffset]$AttemptedAtUtc,

        [Parameter(Mandatory)]
        [string]$StartFailure,

        [Parameter(Mandatory)]
        [psobject]$Outcome,

        [Parameter(Mandatory)]
        [string]$ResourceGroupName,

        [Parameter(Mandatory)]
        [string]$JobName,

        [Parameter(Mandatory)]
        [string]$TargetSubscriptionId
    )

    New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
    $statusPath = Join-Path $artifactDirectory "migration-start-ambiguity.json"
    $statusRecord = [ordered]@{
        startAttemptedAtUtc = $AttemptedAtUtc.ToString("O")
        startFailure = Protect-AzureCliDiagnostics -Text $StartFailure
        exactExecutionName = $Outcome.ExactExecutionName
        exactStopAttempted = $Outcome.ExactStopAttempted
        stopConfirmed = $Outcome.StopConfirmed
        stopStatus = $Outcome.StopStatus
        stopEndTime = $Outcome.StopEndTime
        stopRequestFailure = Protect-AzureCliDiagnostics -Text ([string]$Outcome.StopRequestFailure)
        discoveredCandidates = @($Outcome.DiscoveredCandidates)
        nonterminalExecutions = @($Outcome.NonterminalExecutions)
        lastQueryFailure = Protect-AzureCliDiagnostics -Text ([string]$Outcome.QueryFailure)
        resourceGroupName = $ResourceGroupName
        jobName = $JobName
        subscriptionId = $TargetSubscriptionId
        retryProhibited = $true
        observedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
    }
    $statusRecord | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8
    return $statusPath
}

function Test-JsonEndpoint {
    param(
        [Parameter(Mandatory)]
        [string]$BaseUrl,

        [Parameter(Mandatory)]
        [string]$Path,

        [hashtable]$ExpectedProperties = @{}
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($SmokeTimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri "$BaseUrl$Path" -Method Get -TimeoutSec 30 -SkipHttpErrorCheck
            if ($response.StatusCode -eq 200) {
                $payload = $response.Content | ConvertFrom-Json
                $matches = $true
                foreach ($expected in $ExpectedProperties.GetEnumerator()) {
                    if ($payload.($expected.Key) -ne $expected.Value) {
                        $matches = $false
                    }
                }

                if ($matches) {
                    return
                }
            }
        }
        catch {
            # Retry bounded transient DNS, TLS, cold-start, and JSON parsing failures.
        }

        Start-Sleep -Seconds 5
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    throw "Smoke test failed for $Path after $SmokeTimeoutSeconds seconds."
}

function Test-AnonymousWriteRejected {
    param(
        [Parameter(Mandatory)]
        [string]$BaseUrl
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($SmokeTimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest `
                -Uri "$BaseUrl/api/v1/pipelines" `
                -Method Post `
                -ContentType "application/json" `
                -Body "{}" `
                -TimeoutSec 30 `
                -SkipHttpErrorCheck
            if ($response.StatusCode -eq 401) {
                return
            }

            if ($response.StatusCode -lt 500 -and $response.StatusCode -notin @(408, 429)) {
                throw "Anonymous write returned unexpected HTTP $($response.StatusCode)."
            }
        }
        catch {
            if ($_.Exception.Message -match "unexpected HTTP") {
                throw
            }
        }

        Start-Sleep -Seconds 5
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    throw "Anonymous-write protection did not return HTTP 401 within $SmokeTimeoutSeconds seconds."
}

Invoke-AzureCli -Arguments @(
    "bicep", "build",
    "--file", $mainTemplate,
    "--stdout"
) -TimeoutSeconds 120 | Out-Null

if ($Mode -eq "Build") {
    Invoke-SyntheticParameterBuild
    Write-Host "Local Bicep and parameter compilation passed with synthetic inputs."
    return
}

if ($Mode -eq "Deploy" -and -not $ConfirmDeployment) {
    throw "Deployment is locked. Re-run with -Mode Deploy -ConfirmDeployment only after the deployment checkpoint is approved."
}

if ($Mode -eq "Deploy" -and -not $PSBoundParameters.ContainsKey("DeploymentPrefix")) {
    if (-not (Test-Path -LiteralPath $previewManifestPath)) {
        throw "No what-if manifest exists from which to reuse DeploymentPrefix. Run -Mode WhatIf before deployment."
    }

    try {
        $reviewedPrefixManifest = Get-Content -Raw -LiteralPath $previewManifestPath | ConvertFrom-Json
        $reviewedDeploymentPrefix = [string]$reviewedPrefixManifest.deploymentPrefix
        if ([string]::IsNullOrWhiteSpace($reviewedDeploymentPrefix)) {
            throw "missing deploymentPrefix"
        }
        $DeploymentPrefix = $reviewedDeploymentPrefix
    }
    catch {
        throw "The what-if manifest has no valid DeploymentPrefix to reuse. Run -Mode WhatIf again."
    }

    Write-Host "Using reviewed DeploymentPrefix from the what-if manifest: $DeploymentPrefix"
}

if ([string]::IsNullOrWhiteSpace($SubscriptionId)) {
    throw "Set AZURE_SUBSCRIPTION_ID explicitly before WhatIf or Deploy. Active-subscription fallback is intentionally disabled."
}

$parsedSubscriptionId = [Guid]::Empty
if (-not [Guid]::TryParse($SubscriptionId, [ref]$parsedSubscriptionId)) {
    throw "AZURE_SUBSCRIPTION_ID must be an explicit subscription GUID, not a subscription name or active-context fallback."
}

$pooledDatabaseUrl = Get-RequiredEnvironmentVariable "NEON_POOLED_DATABASE_URL"
$directDatabaseUrl = Get-RequiredEnvironmentVariable "NEON_DIRECT_DATABASE_URL"
$ingestionApiKey = Get-RequiredEnvironmentVariable "DATAOPS_INGESTION_API_KEY"

Assert-DatabaseConnectionPair -PooledUrl $pooledDatabaseUrl -DirectUrl $directDatabaseUrl

if ($ingestionApiKey.Length -lt 24) {
    throw "DATAOPS_INGESTION_API_KEY must contain at least 24 characters."
}

$accountContextJson = (Invoke-AzureCli -Arguments @(
    "account", "show",
    "--subscription", $SubscriptionId,
    "--query", "{id:id,name:name,tenantId:tenantId}",
    "--output", "json"
) -TimeoutSeconds 120) -join [Environment]::NewLine
$accountContext = $accountContextJson | ConvertFrom-Json
if ([string]$accountContext.id -ne $SubscriptionId) {
    throw "Azure resolved a subscription other than the explicit AZURE_SUBSCRIPTION_ID. No preview or deployment was started."
}

Write-Host "Azure target: $($accountContext.name) | subscription $($accountContext.id) | tenant $($accountContext.tenantId)"

foreach ($providerNamespace in @("Microsoft.App")) {
    $providerState = ((Invoke-AzureCli -Arguments @(
        "provider", "show",
        "--namespace", $providerNamespace,
        "--subscription", $SubscriptionId,
        "--query", "registrationState",
        "--output", "tsv"
    ) -TimeoutSeconds 120) -join "").Trim()

    if ($providerState -ne "Registered") {
        throw "$providerNamespace is $providerState. Provider registration requires a separate approved action."
    }
}

$originalDeployApi = [Environment]::GetEnvironmentVariable("AZURE_DEPLOY_API", "Process")
$releaseLock = Enter-ReleaseLock -TargetSubscriptionId $SubscriptionId
Write-Host "Exclusive local release lock acquired: $($releaseLock.Path)"
try {
    if ($Mode -eq "WhatIf") {
        $env:AZURE_DEPLOY_API = "true"
        $whatIfOutput = @(Invoke-AzureCli -Arguments @(
            "deployment", "sub", "what-if",
            "--name", "$DeploymentPrefix-whatif",
            "--location", $location,
            "--parameters", $parameterFile,
            "--subscription", $SubscriptionId,
            "--result-format", "FullResourcePayloads",
            "--no-pretty-print",
            "--no-prompt", "true",
            "--output", "json"
        ) -TimeoutSeconds 900)
        if ($whatIfOutput.Count -eq 0) {
            throw "Azure returned no FullResourcePayloads what-if output; no approval manifest was saved."
        }

        $whatIfJson = Protect-AzureCliDiagnostics -Text ($whatIfOutput -join [Environment]::NewLine)
        try {
            $null = $whatIfJson | ConvertFrom-Json
        }
        catch {
            throw "Azure returned invalid FullResourcePayloads JSON; no approval manifest was saved."
        }

        New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
        [IO.File]::WriteAllText($previewOutputPath, $whatIfJson, [Text.UTF8Encoding]::new($false))
        Write-Host $whatIfJson
        Save-WhatIfManifest `
            -TargetSubscriptionId $SubscriptionId `
            -TargetDeploymentPrefix $DeploymentPrefix `
            -PooledDatabaseUrl $pooledDatabaseUrl `
            -DirectDatabaseUrl $directDatabaseUrl `
            -IngestionApiKey $ingestionApiKey
        Write-Host "What-if completed. Review $previewOutputPath; its hash and deployment-input fingerprints are bound in $previewManifestPath"
        return
    }

    Assert-CurrentWhatIfManifest `
        -TargetSubscriptionId $SubscriptionId `
        -TargetDeploymentPrefix $DeploymentPrefix `
        -PooledDatabaseUrl $pooledDatabaseUrl `
        -DirectDatabaseUrl $directDatabaseUrl `
        -IngestionApiKey $ingestionApiKey

    $env:AZURE_DEPLOY_API = "false"
    $foundationDeploymentName = "$DeploymentPrefix-foundation"
    Invoke-SubscriptionDeployment -DeploymentName $foundationDeploymentName -TargetSubscriptionId $SubscriptionId

    $resourceGroupName = Get-DeploymentOutput `
        -DeploymentName $foundationDeploymentName `
        -OutputName "deployedResourceGroupName" `
        -TargetSubscriptionId $SubscriptionId
    $migrationJobName = Get-DeploymentOutput `
        -DeploymentName $foundationDeploymentName `
        -OutputName "deployedMigrationJobName" `
        -TargetSubscriptionId $SubscriptionId

    $preStartExecutionRecords = @(Get-MigrationExecutionRecords `
        -ResourceGroupName $resourceGroupName `
        -JobName $migrationJobName `
        -TargetSubscriptionId $SubscriptionId)
    $activeExecutions = @(
        $preStartExecutionRecords |
            Where-Object { [string]::IsNullOrWhiteSpace($_.EndTime) } |
            ForEach-Object { $_.Name } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )

    if ($activeExecutions.Count -gt 0) {
        throw "A nonterminal migration execution already exists: $($activeExecutions -join ', '). No new migration was started. Do not retry until every listed execution is terminal."
    }

    $knownExecutionNames = @(
        $preStartExecutionRecords |
            ForEach-Object { $_.Name } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $startAttemptedAtUtc = [DateTimeOffset]::UtcNow
    $startFailure = $null
    $executionName = $null
    try {
        $executionName = ((Invoke-AzureCli -Arguments @(
            "containerapp", "job", "start",
            "--name", $migrationJobName,
            "--resource-group", $resourceGroupName,
            "--subscription", $SubscriptionId,
            "--query", "name",
            "--output", "tsv"
        ) -TimeoutSeconds 120) -join "").Trim()
    }
    catch {
        $startFailure = $_
    }

    if ($null -ne $startFailure -or [string]::IsNullOrWhiteSpace($executionName)) {
        $startException = if ($null -ne $startFailure) {
            $startFailure.Exception
        }
        else {
            [InvalidOperationException]::new("Azure CLI returned a blank migration execution identifier.")
        }
        $startFailureMessage = $startException.Message

        try {
            $ambiguityOutcome = Resolve-AmbiguousMigrationStart `
                -ResourceGroupName $resourceGroupName `
                -JobName $migrationJobName `
                -TargetSubscriptionId $SubscriptionId `
                -AttemptedAtUtc $startAttemptedAtUtc `
                -KnownExecutionNames $knownExecutionNames
        }
        catch {
            $ambiguityOutcome = [pscustomobject]@{
                ExactExecutionName = $null
                ExactStopAttempted = $false
                StopConfirmed = $false
                StopStatus = $null
                StopEndTime = $null
                StopRequestFailure = $null
                DiscoveredCandidates = @()
                NonterminalExecutions = @()
                QueryFailure = "Ambiguity resolver failed: $($_.Exception.Message)"
            }
        }

        $ambiguityArtifactPath = $null
        $ambiguityArtifactFailure = $null
        try {
            $ambiguityArtifactPath = Save-MigrationStartAmbiguity `
                -AttemptedAtUtc $startAttemptedAtUtc `
                -StartFailure $startFailureMessage `
                -Outcome $ambiguityOutcome `
                -ResourceGroupName $resourceGroupName `
                -JobName $migrationJobName `
                -TargetSubscriptionId $SubscriptionId
        }
        catch {
            $ambiguityArtifactFailure = $_.Exception.Message
        }

        $candidateText = if (@($ambiguityOutcome.DiscoveredCandidates).Count -gt 0) {
            @($ambiguityOutcome.DiscoveredCandidates) -join ", "
        }
        else {
            "<none observed>"
        }
        $nonterminalText = if (@($ambiguityOutcome.NonterminalExecutions).Count -gt 0) {
            @($ambiguityOutcome.NonterminalExecutions) -join ", "
        }
        else {
            "<none observed>"
        }

        $message = "Migration start acceptance is AMBIGUOUS. Original error: $startFailureMessage Discovered post-attempt candidates: $candidateText. Last observed nonterminal executions: $nonterminalText."
        if ($ambiguityOutcome.ExactStopAttempted -and $ambiguityOutcome.StopConfirmed) {
            $message += " Exact execution '$($ambiguityOutcome.ExactExecutionName)' was stopped or otherwise reached terminal status '$($ambiguityOutcome.StopStatus)' with endTime '$($ambiguityOutcome.StopEndTime)'."
        }
        elseif ($ambiguityOutcome.ExactStopAttempted) {
            $message += " Stop of exact execution '$($ambiguityOutcome.ExactExecutionName)' is UNCONFIRMED."
        }
        elseif (@($ambiguityOutcome.DiscoveredCandidates).Count -gt 0) {
            $message += " No execution was stopped because no single attributable active execution could be selected safely."
        }
        else {
            $message += " No attributable execution became visible during bounded discovery; this does not prove the start request was rejected."
        }
        if ($null -ne $ambiguityOutcome.StopRequestFailure) {
            $message += " Stop-request error: $($ambiguityOutcome.StopRequestFailure)"
        }
        if ($null -ne $ambiguityOutcome.QueryFailure) {
            $message += " Last discovery/status-query error: $($ambiguityOutcome.QueryFailure)"
        }
        if ($null -ne $ambiguityArtifactPath) {
            $message += " Reconciliation record: $ambiguityArtifactPath."
        }
        elseif ($null -ne $ambiguityArtifactFailure) {
            $message += " Reconciliation-record error: $ambiguityArtifactFailure"
        }
        $message += " The API was not deployed. Do not retry until every discovered candidate and every nonterminal execution for job '$migrationJobName' has a non-null endTime, and the exact job execution list has been checked after Azure propagation."

        throw [InvalidOperationException]::new($message, $startException)
    }

    $migrationStatus = "Unknown"
    $migrationEndTime = $null
    $migrationTerminalConfirmed = $false
    try {
        $activeExecutionsAfterStart = @(Get-ActiveMigrationExecutionNames `
            -ResourceGroupName $resourceGroupName `
            -JobName $migrationJobName `
            -TargetSubscriptionId $SubscriptionId)
        $otherActiveExecutions = @(
            $activeExecutionsAfterStart | Where-Object { $_ -cne $executionName }
        )
        if ($otherActiveExecutions.Count -gt 0) {
            throw "Concurrent migration executions were detected: $($otherActiveExecutions -join ', ')."
        }

        $deadline = [DateTimeOffset]::UtcNow.AddSeconds($MigrationTimeoutSeconds)
        $lastStatusQueryFailure = $null
        while ([DateTimeOffset]::UtcNow -lt $deadline) {
            try {
                $observation = Get-MigrationExecutionObservation `
                    -ResourceGroupName $resourceGroupName `
                    -JobName $migrationJobName `
                    -ExecutionName $executionName `
                    -TargetSubscriptionId $SubscriptionId `
                    -TimeoutSeconds 60
                $migrationStatus = $observation.Status
                $migrationEndTime = $observation.EndTime
                $lastStatusQueryFailure = $null
            }
            catch {
                $lastStatusQueryFailure = $_.Exception.Message
                Start-Sleep -Seconds 5
                continue
            }

            if (-not [string]::IsNullOrWhiteSpace($migrationEndTime)) {
                $migrationTerminalConfirmed = $true
                break
            }

            Start-Sleep -Seconds 5
        }

        if (-not $migrationTerminalConfirmed) {
            $queryDetail = if ($null -ne $lastStatusQueryFailure) { " Last status-query error: $lastStatusQueryFailure" } else { "" }
            throw "Migration execution '$executionName' exceeded its $MigrationTimeoutSeconds-second release timeout.$queryDetail"
        }

        Save-ExecutionStatus `
            -ExecutionName $executionName `
            -Status $migrationStatus `
            -ResourceGroupName $resourceGroupName `
            -JobName $migrationJobName `
            -TargetSubscriptionId $SubscriptionId
        if ($migrationStatus -ne "Succeeded") {
            throw "Migration execution ended with status '$migrationStatus'. The API was not deployed."
        }
    }
    catch {
        $migrationPhaseFailure = $_
        if ($migrationTerminalConfirmed) {
            throw
        }

        try {
            $stopResult = Stop-MigrationExecutionAndConfirm `
                -ResourceGroupName $resourceGroupName `
                -JobName $migrationJobName `
                -ExecutionName $executionName `
                -TargetSubscriptionId $SubscriptionId
        }
        catch {
            $stopResult = [pscustomobject]@{
                Confirmed = $false
                Status = $migrationStatus
                EndTime = $migrationEndTime
                StopRequestFailure = "Stop-confirmation helper failed: $($_.Exception.Message)"
                LastQueryFailure = $null
            }
        }

        $recordedStatus = if ($stopResult.Confirmed) { $stopResult.Status } else { "StopUnconfirmed" }
        $statusSaveFailure = $null
        try {
            Save-ExecutionStatus `
                -ExecutionName $executionName `
                -Status $recordedStatus `
                -ResourceGroupName $resourceGroupName `
                -JobName $migrationJobName `
                -TargetSubscriptionId $SubscriptionId `
                -TerminalStateConfirmed $stopResult.Confirmed
        }
        catch {
            $statusSaveFailure = $_.Exception.Message
        }

        $message = "Migration phase failed after starting exact execution '$executionName'. Original error: $($migrationPhaseFailure.Exception.Message)"
        if ($stopResult.Confirmed) {
            $message += " Stop handling confirmed endTime '$($stopResult.EndTime)' and terminal status '$($stopResult.Status)'. The API was not deployed."
        }
        else {
            $stopDetail = if ($null -ne $stopResult.StopRequestFailure) { " Stop-request error: $($stopResult.StopRequestFailure)" } else { "" }
            $queryDetail = if ($null -ne $stopResult.LastQueryFailure) { " Last status-query error: $($stopResult.LastQueryFailure)" } else { "" }
            $message += " Stop is UNCONFIRMED.$stopDetail$queryDetail The API was not deployed. Do not retry until Azure reports a non-null endTime for this exact execution."
        }
        if ($null -ne $statusSaveFailure) {
            $message += " Status-artifact error: $statusSaveFailure"
        }

        throw [InvalidOperationException]::new($message, $migrationPhaseFailure.Exception)
    }

    $env:AZURE_DEPLOY_API = "true"
    $apiDeploymentName = "$DeploymentPrefix-api"
    Invoke-SubscriptionDeployment -DeploymentName $apiDeploymentName -TargetSubscriptionId $SubscriptionId
    $apiBaseUrl = Get-DeploymentOutput `
        -DeploymentName $apiDeploymentName `
        -OutputName "apiUrl" `
        -TargetSubscriptionId $SubscriptionId

    try {
        Test-JsonEndpoint -BaseUrl $apiBaseUrl -Path "/live" -ExpectedProperties @{ status = "ok" }
        Test-JsonEndpoint -BaseUrl $apiBaseUrl -Path "/health" -ExpectedProperties @{ status = "ok"; database = "ok" }
        Test-JsonEndpoint -BaseUrl $apiBaseUrl -Path "/api/v1/pipelines"
        Test-AnonymousWriteRejected -BaseUrl $apiBaseUrl
    }
    catch {
        Write-Warning "Azure deployment succeeded, but smoke validation failed. The release is non-atomic; inspect the active revision and roll back or disable ingress before advertising the endpoint."
        throw
    }

    Write-Host "Release succeeded: $apiBaseUrl"
}
finally {
    if ($null -ne $releaseLock) {
        $releaseLock.Stream.Dispose()
    }
    [Environment]::SetEnvironmentVariable("AZURE_DEPLOY_API", $originalDeployApi, "Process")
}
