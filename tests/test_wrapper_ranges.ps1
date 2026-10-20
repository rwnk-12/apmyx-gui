[CmdletBinding()]
param([switch]$Benchmark)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $repository 'scripts/wrappers/modules/Progress.psm1') -Force
Import-Module (Join-Path $repository 'scripts/wrappers/modules/RangeDownload.psm1') -Force
$temporary = Join-Path $repository ('build/range-tests-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$checks = 0
$results = @()
try {
    $modes = if ($Benchmark) { @('single', 'parallel') } else { @('integration', 'integration-fallback', 'integration-weak', 'integration-400', 'wrong-range', 'changed-etag', 'disconnect', 'stall') }
    foreach ($mode in $modes) {
        $connections = if ($mode -eq 'single') { 1 } else { 4 }
        $size = if ($Benchmark) { 8MB } elseif ($mode.StartsWith('integration')) { 32MB + 3 } else { 1MB + 3 }
        $delay = if ($Benchmark) { 10 } else { 0 }
        $manifestPath = Join-Path $temporary "$mode.json"
        $server = Start-Job -ScriptBlock {
            param($ManifestPath, $Mode, $Size, $Connections, $Delay)
            function Read-Request($Client) {
                $stream = $Client.GetStream()
                $reader = [IO.StreamReader]::new($stream)
                $start = 0L; $end = 0L; $etag = ''
                while ($line = $reader.ReadLine()) {
                    if ($line -match '^Range: bytes=(\d+)-(\d+)$') { $start = [long]$Matches[1]; $end = [long]$Matches[2] }
                    if ($line -match '^If-Match: (.+)$') { $etag = $Matches[1] }
                }
                [pscustomobject]@{ Client = $Client; Stream = $stream; Start = $start; End = $end; ETag = $etag; Sent = 0L }
            }
            $payload = [byte[]]::new($Size)
            for ($i = 0; $i -lt $Size; $i += 4096) { $payload[$i] = ($i / 4096) % 251 }
            $payload[$Size - 1] = 239
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $hash = ([BitConverter]::ToString($sha.ComputeHash($payload))).Replace('-', '') } finally { $sha.Dispose() }
            $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
            $listener.Start()
            @{ Port = $listener.LocalEndpoint.Port; Hash = $hash } | ConvertTo-Json | Set-Content -LiteralPath $ManifestPath
            $clients = @()
            try {
                if ($Mode.StartsWith('integration')) {
                    $probe = $listener.AcceptTcpClient()
                    try {
                        $request = Read-Request $probe
                        $etag = if ($Mode -eq 'integration-weak') { 'W/"fixture"' } else { '"fixture"' }
                        $header = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 206 Partial Content`r`nContent-Length: 1`r`nContent-Range: bytes 0-0/$Size`r`nETag: $etag`r`nConnection: close`r`n`r`n")
                        $request.Stream.Write($header, 0, $header.Length)
                        $request.Stream.Write($payload, 0, 1)
                    } finally { $probe.Dispose() }
                }
                $rangeConnections = if ($Mode -eq 'integration-weak') { 0 } else { $Connections }
                for ($i = 0; $i -lt $rangeConnections; $i++) {
                    $client = $listener.AcceptTcpClient()
                    $client.NoDelay = $true
                    $clients += Read-Request $client
                }
                foreach ($request in $clients) {
                    if ($request.ETag -ne '"fixture"') { throw 'Range request omitted its identity precondition.' }
                    $rangeStart = if ($Mode -in @('wrong-range', 'integration-fallback')) { $request.Start + 1 } else { $request.Start }
                    $etag = if ($Mode -eq 'changed-etag') { 'changed' } else { 'fixture' }
                    $length = $request.End - $request.Start + 1
                    $header = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 206 Partial Content`r`nContent-Length: $length`r`nContent-Range: bytes $rangeStart-$($request.End)/$Size`r`nETag: `"$etag`"`r`nConnection: close`r`n`r`n")
                    if ($Mode -eq 'integration-400') { $header = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 400 Bad Request`r`nContent-Length: 0`r`nConnection: close`r`n`r`n") }
                    try { $request.Stream.Write($header, 0, $header.Length) } catch { if ($Mode -notin @('integration-fallback', 'integration-400')) { throw } }
                }
                if ($Mode -in @('integration-fallback', 'integration-weak', 'integration-400')) {
                    foreach ($request in $clients) { $request.Client.Dispose() }
                    $clients = @()
                    $client = $listener.AcceptTcpClient()
                    $request = Read-Request $client
                    $clients += $request
                    $header = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 200 OK`r`nContent-Length: $Size`r`nConnection: close`r`n`r`n")
                    $request.Stream.Write($header, 0, $header.Length)
                    $request.Stream.Write($payload, 0, $payload.Length)
                    return
                }
                if ($Mode -eq 'stall') { Start-Sleep -Seconds 10; return }
                if ($Mode -in @('wrong-range', 'changed-etag')) { return }
                $pending = $true
                while ($pending) {
                    $pending = $false
                    foreach ($request in $clients) {
                        $length = $request.End - $request.Start + 1
                        if ($Mode -eq 'disconnect') { $length = [long][Math]::Floor($length / 2) }
                        if ($request.Sent -ge $length) { continue }
                        $count = [int][Math]::Min($length - $request.Sent, $(if ($Delay) { 64KB } else { $length }))
                        $request.Stream.Write($payload, [int]($request.Start + $request.Sent), $count)
                        $request.Sent += $count
                        if ($request.Sent -lt $length) { $pending = $true }
                    }
                    if ($pending -and $Delay) { Start-Sleep -Milliseconds $Delay }
                }
            } finally {
                foreach ($request in $clients) { $request.Client.Dispose() }
                $listener.Stop()
            }
        } -ArgumentList $manifestPath, $mode, $size, $connections, $delay
        try {
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            while (-not (Test-Path $manifestPath) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
            if (-not (Test-Path $manifestPath)) { throw 'Range test server did not start.' }
            $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
            $path = Join-Path $temporary "$mode.bin"
            $timer = [Diagnostics.Stopwatch]::StartNew()
            $failed = $false
            try {
                if ($mode.StartsWith('integration')) {
                    Save-SetupDownload -Url "http://127.0.0.1:$($manifest.Port)/fixture" -Path $path -Label $mode -ExpectedBytes $size -MaxAttempts 1
                    $success = $true
                } else {
                    $success = Save-RangedSetupDownload -Url "http://127.0.0.1:$($manifest.Port)/fixture" -Path $path -Label $mode -Size $size -ETag '"fixture"' -Connections $connections -StallSeconds 2
                }
            } catch {
                if ($mode -notin @('disconnect', 'stall')) { throw }
                $failed = $true
            }
            $timer.Stop()
            if ($mode.StartsWith('integration') -or $mode -in @('single', 'parallel')) {
                if (-not $success -or (Get-FileHash $path -Algorithm SHA256).Hash -ne $manifest.Hash) { throw 'Range merge failed checksum verification.' }
                $results += [pscustomobject]@{ Mode = $mode; Connections = $connections; Seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3); MBps = [Math]::Round($size / 1MB / $timer.Elapsed.TotalSeconds, 2); SHA256Verified = $true }
                $checks++
            } elseif ($mode -in @('wrong-range', 'changed-etag')) {
                if ($success -or (Test-Path $path)) { throw 'Incompatible ranges were accepted.' }
                $checks++
            } elseif (-not $failed -or (Test-Path $path)) { throw 'Broken ranges were accepted.' } else { $checks++ }
            if (@(Get-ChildItem $temporary -Filter '*.part-*').Count) { throw 'Range download left temporary part files.' }
            $checks++
        } finally {
            if ($server.State -in @('NotStarted', 'Running')) { Stop-Job $server }
            Remove-Job $server
        }
    }
    $results | ConvertTo-Json -Depth 3 | Write-Output
    Write-Host "$checks range download checks passed. Local HTTP fixtures only."
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    $buildRoot = [IO.Path]::GetFullPath((Join-Path $repository 'build')) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($buildRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe range test cleanup path.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
