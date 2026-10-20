Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Progress.psm1')

function Save-RangedSetupDownload {
    param([string]$Url, [string]$Path, [string]$Label, [long]$Size, [string]$ETag, [int]$StallSeconds = 90, [ValidateRange(1, 4)][int]$Connections = 4)
    $parts = @()
    $output = $null
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextUpdate = 5
    $chunk = [long][Math]::Ceiling($Size / [double]$Connections)
    Write-SetupStatus "${Label}: using $Connections parallel download connections."
    try {
        for ($index = 0; $index -lt $Connections; $index++) {
            $start = $index * $chunk
            $end = [Math]::Min($Size - 1, $start + $chunk - 1)
            $request = [Net.HttpWebRequest]::Create($Url)
            $request.UserAgent = 'apmyx-wrapper-setup'
            $request.KeepAlive = $false
            $request.ServicePoint.ConnectionLimit = [Math]::Max($Connections, $request.ServicePoint.ConnectionLimit)
            $request.AddRange($start, $end)
            $request.Headers['If-Match'] = $ETag
            $part = [pscustomobject]@{ Path = "$Path.part-$index"; Start = $start; End = $end; Request = $request; Headers = $null; Response = $null; Stream = $null; File = $null; Copy = $null; Bytes = 0L; LastActivity = 0.0; Done = $false }
            $parts += $part
            $part.Headers = $request.GetResponseAsync()
        }
        while (@($parts | Where-Object { -not $_.Done }).Count) {
            foreach ($part in $parts) {
                if ($part.Done) { continue }
                if (-not $part.Response -and $part.Headers.IsCompleted) {
                    try { $part.Response = $part.Headers.GetAwaiter().GetResult() } catch {
                        $cause = $_.Exception
                        while ($cause) {
                            if ($cause -is [Net.WebException] -and $cause.Response -is [Net.HttpWebResponse] -and [int]$cause.Response.StatusCode -in @(400, 405, 412, 416, 501)) {
                                $cause.Response.Dispose()
                                Write-SetupStatus 'The server rejected parallel ranges. Switching to a single download stream.'
                                return $false
                            }
                            $cause = $cause.InnerException
                        }
                        throw
                    }
                    $expectedRange = "bytes $($part.Start)-$($part.End)/$Size"
                    if ([int]$part.Response.StatusCode -ne 206 -or $part.Response.Headers['Content-Range'] -ne $expectedRange -or $part.Response.Headers['ETag'] -ne $ETag) {
                        Write-SetupStatus 'The server changed its range response. Switching to a single download stream.'
                        return $false
                    }
                    $length = $part.End - $part.Start + 1
                    if ($part.Response.ContentLength -ge 0 -and $part.Response.ContentLength -ne $length) { throw 'Server returned an incompatible download range size.' }
                    $part.Stream = $part.Response.GetResponseStream()
                    $options = [IO.FileOptions]::Asynchronous -bor [IO.FileOptions]::SequentialScan
                    $part.File = [IO.FileStream]::new($part.Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read, 1, $options)
                    $part.Copy = $part.Stream.CopyToAsync($part.File, 1MB)
                    $part.LastActivity = $timer.Elapsed.TotalSeconds
                }
                if ($part.Copy) {
                    $bytes = ([IO.FileInfo]::new($part.Path)).Length
                    if ($bytes -gt $part.Bytes) { $part.Bytes = $bytes; $part.LastActivity = $timer.Elapsed.TotalSeconds }
                    if ($part.Copy.IsCompleted) {
                        $part.Copy.GetAwaiter().GetResult() | Out-Null
                        $part.File.Flush()
                        $part.Bytes = $part.File.Length
                        if ($part.Bytes -ne ($part.End - $part.Start + 1)) { throw 'A parallel download connection closed before its range was complete.' }
                        $part.Done = $true
                    }
                }
                if (-not $part.Done -and $timer.Elapsed.TotalSeconds - $part.LastActivity -ge $StallSeconds) { throw 'A parallel download connection stalled.' }
            }
            if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                $received = ($parts | Measure-Object Bytes -Sum).Sum
                Write-DownloadStatus $Label $received $Size $timer.Elapsed.TotalSeconds
                $nextUpdate += 5
            }
            if (@($parts | Where-Object { -not $_.Done }).Count) { Start-Sleep -Milliseconds 50 }
        }
        Write-SetupStatus "${Label}: joining downloaded ranges..."
        $options = [IO.FileOptions]::Asynchronous -bor [IO.FileOptions]::SequentialScan
        $output = [IO.FileStream]::new($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read, 1, $options)
        foreach ($part in $parts) {
            $part.File.Dispose()
            $part.File = $null
            $inputFile = [IO.File]::OpenRead($part.Path)
            try {
                $merge = $inputFile.CopyToAsync($output, 1MB)
                while (-not $merge.Wait(1000)) {
                    if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
                        Write-SetupStatus "Joining $Label ranges ($([int]$timer.Elapsed.TotalSeconds)s elapsed)..."
                        $nextUpdate += 5
                    }
                }
                $merge.GetAwaiter().GetResult() | Out-Null
            } finally { $inputFile.Dispose() }
        }
        $output.Flush()
        if ($output.Length -ne $Size) { throw 'Merged download size does not match the server package size.' }
        Write-SetupStatus "$Label download complete ($([int]$timer.Elapsed.TotalSeconds)s elapsed)."
        return $true
    } finally {
        if ($output) { $output.Dispose() }
        foreach ($part in $parts) {
            $part.Request.Abort()
            if ($part.Stream) { $part.Stream.Dispose() }
            if ($part.Copy -and -not $part.Copy.IsCompleted) { try { $part.Copy.Wait(1000) | Out-Null } catch { } }
            if ($part.File) { $part.File.Dispose() }
            if ($part.Response) { $part.Response.Dispose() }
            if (Test-Path -LiteralPath $part.Path) { Remove-Item -LiteralPath $part.Path -Force }
        }
        $timer.Stop()
    }
}

Export-ModuleMember -Function Save-RangedSetupDownload
