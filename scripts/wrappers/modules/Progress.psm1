Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:logPath = $null

function Initialize-SetupProgress {
    param([string]$Path)
    $script:logPath = $Path
    Write-SetupStatus "Progress log: $Path"
}

function Write-SetupStatus {
    param([string]$Message, [switch]$Failure)
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $Message
    if ($Failure) { Write-Host $line -ForegroundColor Red } else { Write-Host $line }
    if ($script:logPath) { [IO.File]::AppendAllText($script:logPath, $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false)) }
}

function ConvertTo-ProcessArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Invoke-SetupProbe {
    param([string]$FilePath, [string[]]$Arguments, [string]$Label, [int]$TimeoutSeconds = 30, [int]$HeartbeatSeconds = 10)
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FilePath
    $info.Arguments = ($Arguments | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextUpdate = $HeartbeatSeconds
    $started = $false
    try {
        $process.Start() | Out-Null
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        while (-not $process.WaitForExit(250)) {
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                throw "$Label timed out after $TimeoutSeconds seconds. Only this diagnostic command will be stopped. Check WSL/Docker Desktop and restart Windows if setup requested it, then rerun."
            }
            if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                Write-SetupStatus "$Label is still running ($([int]$timer.Elapsed.TotalSeconds)s elapsed)..."
                $nextUpdate += $HeartbeatSeconds
            }
        }
        if (-not $stdout.Wait(1000) -or -not $stderr.Wait(1000)) { throw "$Label exited but its output did not close. Rerun after checking WSL/Docker Desktop." }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout.GetAwaiter().GetResult(); Stderr = $stderr.GetAwaiter().GetResult() }
    } finally {
        if ($started -and -not $process.HasExited) {
            $stopInfo = [Diagnostics.ProcessStartInfo]::new()
            $stopInfo.FileName = Join-Path $env:SystemRoot 'System32/taskkill.exe'
            $stopInfo.Arguments = "/PID $($process.Id) /T /F"
            $stopInfo.UseShellExecute = $false
            $stopInfo.CreateNoWindow = $true
            $stopInfo.RedirectStandardOutput = $true
            $stopInfo.RedirectStandardError = $true
            $stopper = [Diagnostics.Process]::Start($stopInfo)
            try {
                if (-not $stopper.WaitForExit(5000)) { $stopper.Kill() }
            } finally { $stopper.Dispose() }
            if (-not $process.HasExited) { $process.Kill() }
            $process.WaitForExit(2000) | Out-Null
        }
        $process.Dispose()
        $timer.Stop()
    }
}

function Wait-SetupInstaller {
    param($Process, [string]$Label, [string]$LogPath, [int]$TimeoutSeconds = 1800, [int]$HeartbeatSeconds = 10)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextUpdate = $HeartbeatSeconds
    $logLength = 0
    try {
        Write-SetupStatus "$Label started (PID $($Process.Id))."
        while (-not $Process.WaitForExit(500)) {
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                throw "$Label is still running after $TimeoutSeconds seconds (PID $($Process.Id)). It has been left running. Check its installer log before starting another setup."
            }
            if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                Write-SetupStatus "Waiting for $Label ($([int]$timer.Elapsed.TotalSeconds)s elapsed, PID $($Process.Id))..."
                if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
                    $file = Get-Item -LiteralPath $LogPath
                    if ($file.Length -ne $logLength) {
                        $logLength = $file.Length
                        Get-Content -LiteralPath $LogPath -Tail 4 -ErrorAction SilentlyContinue | ForEach-Object { Write-SetupStatus "  $($_)" }
                    }
                }
                $nextUpdate += $HeartbeatSeconds
            }
        }
        Write-SetupStatus "$Label finished (exit $($Process.ExitCode), $([int]$timer.Elapsed.TotalSeconds)s elapsed)."
        return $Process.ExitCode
    } finally {
        $Process.Dispose()
        $timer.Stop()
    }
}

function Get-SetupSignature {
    param([string]$Path, [int]$TimeoutSeconds = 90)
    Write-SetupStatus 'Verifying the Docker installer signature. Windows may contact its certificate servers...'
    $job = Start-Job -ScriptBlock {
        param($InstallerPath)
        $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
        $subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { '' }
        [pscustomobject]@{ Status = [string]$signature.Status; Subject = $subject }
    } -ArgumentList $Path
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextUpdate = 10
    try {
        while ($job.State -in @('NotStarted', 'Running')) {
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) { throw 'Docker installer signature verification timed out. Check connectivity to Windows certificate/revocation servers, then rerun. Signature verification was not bypassed.' }
            if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                Write-SetupStatus "Still checking the installer signature ($([int]$timer.Elapsed.TotalSeconds)s elapsed)..."
                $nextUpdate += 10
            }
            $job | Wait-Job -Timeout 1 | Out-Null
        }
        if ($job.State -ne 'Completed') { throw 'Windows could not verify the Docker installer signature.' }
        return Receive-Job -Job $job -ErrorAction Stop
    } finally {
        if ($job.State -in @('NotStarted', 'Running')) { Stop-Job -Job $job }
        Remove-Job -Job $job
        $timer.Stop()
    }
}

function Save-SetupDownload {
    param([string]$Url, [string]$Path, [string]$Label, [int]$StallSeconds = 90, [long]$ExpectedBytes = -1, [ValidateRange(1, 10)][int]$MaxAttempts = 3, [ValidateRange(0, 60)][int]$RetryDelaySeconds = 2)
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        Write-SetupStatus "Downloading $Label (attempt $attempt/$MaxAttempts)..."
        try {
            Save-SetupDownloadAttempt -Url $Url -Path $Path -Label $Label -StallSeconds $StallSeconds -ExpectedBytes $ExpectedBytes
            return
        } catch {
            $failure = $_.Exception
            $retryable = $false
            while ($failure) {
                if ($failure.Data.Contains('DownloadRetryable')) {
                    $retryable = [bool]$failure.Data['DownloadRetryable']
                    break
                }
                $failure = $failure.InnerException
            }
            $reason = $_.Exception.GetBaseException().Message.TrimEnd('.')
            if (-not $retryable -or $attempt -eq $MaxAttempts) {
                throw "${Label} download failed after $attempt attempt(s): $reason. Rerun setup to try again; completed verified packages are cached."
            }
            $delay = [int]($RetryDelaySeconds * [Math]::Pow(2, $attempt - 1))
            Write-SetupStatus "${Label} connection failed: $reason. Retrying from the beginning in ${delay}s..."
            if ($delay) { Start-Sleep -Seconds $delay }
        }
    }
}

function Save-SetupDownloadAttempt {
    param([string]$Url, [string]$Path, [string]$Label, [int]$StallSeconds, [long]$ExpectedBytes)
    $request = [Net.HttpWebRequest]::Create($Url)
    $request.UserAgent = 'apmyx-wrapper-setup'
    $request.KeepAlive = $false
    if ($env:APMYX_SETUP_SINGLE_STREAM -ne '1') { $request.AddRange(0, 0) }
    $response = $null
    $stream = $null
    $file = $null
    $copy = $null
    $cancellation = $null
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $lastActivity = $timer.Elapsed.TotalSeconds
    $nextUpdate = 5
    $received = 0L
    $phase = 'connecting'
    try {
        $headers = $request.GetResponseAsync()
        while (-not $headers.Wait(200)) {
            if ($timer.Elapsed.TotalSeconds -ge $StallSeconds) { throw "Download connection timed out after ${StallSeconds}s. Check your connection, proxy, or firewall and rerun." }
            if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                Write-SetupStatus "Waiting for $Label download server ($([int]$timer.Elapsed.TotalSeconds)s elapsed)..."
                $nextUpdate += 5
            }
        }
        $response = $headers.GetAwaiter().GetResult()
        if ([int]$response.StatusCode -eq 206) {
            $range = $response.Headers['Content-Range']
            $etag = $response.Headers['ETag']
            $size = if ($range -match '^bytes 0-0/(\d+)$') { [long]$Matches[1] } else { -1L }
            if ($ExpectedBytes -ge 0 -and $size -ge 0 -and $ExpectedBytes -ne $size) { $phase = 'validating headers'; throw 'Server package size does not match the pinned package size.' }
            $response.Dispose()
            $response = $null
            $request.Abort()
            if ($size -ge 32MB -and $etag -and -not $etag.StartsWith('W/') -and $etag.StartsWith('"')) {
                Import-Module (Join-Path $PSScriptRoot 'RangeDownload.psm1')
                $phase = 'copying'
                if (Save-RangedSetupDownload -Url $Url -Path $Path -Label $Label -Size $size -ETag $etag -StallSeconds $StallSeconds) { return }
            }
            $request = [Net.HttpWebRequest]::Create($Url)
            $request.UserAgent = 'apmyx-wrapper-setup'
            $request.KeepAlive = $false
            $phase = 'connecting'
            $headers = $request.GetResponseAsync()
            $started = $timer.Elapsed.TotalSeconds
            while (-not $headers.Wait(200)) {
                if ($timer.Elapsed.TotalSeconds - $started -ge $StallSeconds) { throw 'Download connection timed out while starting the single stream.' }
            }
            $response = $headers.GetAwaiter().GetResult()
            if ([int]$response.StatusCode -ne 200) { $phase = 'validating headers'; throw 'Server did not return a complete download stream.' }
        }
        $phase = 'validating headers'
        if ($ExpectedBytes -ge 0 -and $response.ContentLength -ge 0 -and $response.ContentLength -ne $ExpectedBytes) {
            throw "Server returned $($response.ContentLength) bytes; the pinned package requires $ExpectedBytes bytes."
        }
        $total = if ($response.ContentLength -ge 0) { $response.ContentLength } else { $ExpectedBytes }
        $phase = 'reading'
        $stream = $response.GetResponseStream()
        $phase = 'opening file'
        $options = [IO.FileOptions]::Asynchronous -bor [IO.FileOptions]::SequentialScan
        $file = [IO.FileStream]::new($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read, 1, $options)
        $metadata = [IO.FileInfo]::new($Path)
        $cancellation = [Threading.CancellationTokenSource]::new()
        $lastActivity = $timer.Elapsed.TotalSeconds
        $phase = 'copying'
        $copy = $stream.CopyToAsync($file, 1MB, $cancellation.Token)
        while (-not $copy.Wait(250)) {
            $metadata.Refresh()
            if ($metadata.Length -gt $received) {
                $received = $metadata.Length
                $lastActivity = $timer.Elapsed.TotalSeconds
            } elseif ($timer.Elapsed.TotalSeconds - $lastActivity -ge $StallSeconds) {
                throw "Download stalled: no bytes received for ${StallSeconds}s. Check your connection and rerun setup."
            }
            if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                Write-DownloadStatus $Label $received $total $timer.Elapsed.TotalSeconds
                $nextUpdate += 5
            }
        }
        $copy.GetAwaiter().GetResult() | Out-Null
        $file.Flush()
        $received = $file.Length
        $phase = 'reading'
        if ($total -ge 0 -and $received -ne $total) { throw "Download ended after $received of $total bytes; the connection closed before the complete file was received." }
        Write-DownloadStatus $Label $received $total $timer.Elapsed.TotalSeconds
        Write-SetupStatus "$Label download complete."
    } catch {
        $retryable = $phase -in @('connecting', 'reading', 'copying')
        $cause = $_.Exception
        while ($cause) {
            if ($cause -is [UnauthorizedAccessException] -or ($cause -is [IO.IOException] -and ($cause.HResult -band 0xFFFF) -in @(5, 19, 21, 23, 27, 29, 32, 33, 39, 112, 206))) { $retryable = $false }
            if ($cause -is [Net.WebException]) {
                if ($cause.Status -in @([Net.WebExceptionStatus]::TrustFailure, [Net.WebExceptionStatus]::SecureChannelFailure)) { $retryable = $false }
                if ($cause.Response -is [Net.HttpWebResponse]) {
                    $status = [int]$cause.Response.StatusCode
                    $retryable = $status -in @(408, 429, 500, 502, 503, 504)
                    $cause.Response.Dispose()
                }
            }
            $cause = $cause.InnerException
        }
        $failure = [InvalidOperationException]::new($_.Exception.GetBaseException().Message, $_.Exception)
        $failure.Data['DownloadRetryable'] = $retryable
        throw $failure
    } finally {
        if ($cancellation) { $cancellation.Cancel() }
        $request.Abort()
        if ($stream) { $stream.Dispose() }
        if ($copy -and -not $copy.IsCompleted) {
            try { $copy.Wait(1000) | Out-Null } catch { }
        }
        if ($file) { $file.Dispose() }
        if ($response) { $response.Dispose() }
        if ($cancellation) { $cancellation.Dispose() }
        $timer.Stop()
    }
}

function Write-DownloadStatus {
    param([string]$Label, [long]$Received, [long]$Total, [double]$Seconds)
    $size = '{0:N1} MB' -f ($Received / 1MB)
    if ($Total -gt 0) { $size += ' / {0:N1} MB ({1:N0}%)' -f ($Total / 1MB), (100 * $Received / $Total) }
    $rate = $Received / [Math]::Max(0.01, $Seconds)
    $speed = if ($rate -lt 1MB) { '{0:N1} KB/s' -f ($rate / 1KB) } else { '{0:N1} MB/s' -f ($rate / 1MB) }
    Write-SetupStatus "${Label}: $size, $speed, $([int]$Seconds)s elapsed"
}

Export-ModuleMember -Function Initialize-SetupProgress, Write-SetupStatus, Write-DownloadStatus, ConvertTo-ProcessArgument, Invoke-SetupProbe, Wait-SetupInstaller, Get-SetupSignature, Save-SetupDownload
