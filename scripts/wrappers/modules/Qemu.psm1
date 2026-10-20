Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Packages.psm1')
Import-Module (Join-Path $PSScriptRoot 'Progress.psm1')

function New-QemuInitramfs {
    param([string]$Original, [string]$InitScript, [string]$Destination)
    $scriptBytes = [Text.Encoding]::UTF8.GetBytes(([IO.File]::ReadAllText($InitScript) -replace "`r`n", "`n"))
    $archive = [IO.MemoryStream]::new()
    try {
        foreach ($entry in @(@('init', $scriptBytes, 33261), @('TRAILER!!!', [byte[]]@(), 0))) {
            $name = [Text.Encoding]::ASCII.GetBytes($entry[0] + [char]0)
            $data = [byte[]]$entry[1]
            $fields = @(1, $entry[2], 0, 0, 1, 0, $data.Length, 0, 0, 0, 0, $name.Length, 0)
            $header = [Text.Encoding]::ASCII.GetBytes('070701' + (($fields | ForEach-Object { '{0:x8}' -f [int]$_ }) -join ''))
            $archive.Write($header, 0, $header.Length)
            $archive.Write($name, 0, $name.Length)
            while ($archive.Position % 4) { $archive.WriteByte(0) }
            $archive.Write($data, 0, $data.Length)
            while ($archive.Position % 4) { $archive.WriteByte(0) }
        }
        $output = [IO.File]::Create($Destination + '.partial')
        try {
            $inputFile = [IO.File]::OpenRead($Original)
            try { $inputFile.CopyTo($output) } finally { $inputFile.Dispose() }
            $gzip = [IO.Compression.GZipStream]::new($output, [IO.Compression.CompressionMode]::Compress, $true)
            try { $archive.Position = 0; $archive.CopyTo($gzip) } finally { $gzip.Dispose() }
        } finally { $output.Dispose() }
        Move-Item -LiteralPath ($Destination + '.partial') -Destination $Destination -Force
    } finally {
        $archive.Dispose()
        if (Test-Path -LiteralPath ($Destination + '.partial')) { Remove-Item -LiteralPath ($Destination + '.partial') }
    }
}

function Protect-QemuSessionDirectory {
    param([string]$Path)
    $directory = [IO.DirectoryInfo]::new($Path)
    $acl = $directory.GetAccessControl([Security.AccessControl.AccessControlSections]::Access)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))) {
        [void]$acl.RemoveAccessRuleSpecific($rule)
    }
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    $directory.SetAccessControl($acl)
}

function Initialize-LiteQemu {
    param([string]$Runtime, [string]$Scripts)
    $source = Get-Content -LiteralPath (Join-Path $Scripts 'qemu/source.json') -Raw | ConvertFrom-Json
    $archive = Join-Path $Runtime 'package.zip'
    Get-VerifiedDownload -Url $source.url -Path $archive -Sha256 $source.sha256 -ExpectedBytes $source.size
    $package = Join-Path $Runtime 'package'
    Expand-SafeArchive -Path $archive -Destination $package
    foreach ($name in @('qemu/bin/qemu-system-x86_64.exe', 'qemu/bin/bios-256k.bin', 'qemu/vmlinuz-lite-qemu', 'qemu/lite-initramfs.cpio.gz', 'qemu/data.img')) {
        if (-not (Test-Path -LiteralPath (Join-Path $package $name) -PathType Leaf)) { throw "The pinned QEMU package is missing $name." }
    }
    $session = Join-Path $Runtime 'session'
    [IO.Directory]::CreateDirectory($session) | Out-Null
    Protect-QemuSessionDirectory $session
    $disk = Join-Path $session 'data.img'
    if (-not (Test-Path -LiteralPath $disk)) { Copy-Item -LiteralPath (Join-Path $package 'qemu/data.img') -Destination $disk }
    New-QemuInitramfs -Original (Join-Path $package 'qemu/lite-initramfs.cpio.gz') -InitScript (Join-Path $Scripts 'qemu/init') -Destination (Join-Path $Runtime 'apmyx-initramfs.cpio.gz')
    @{ revision = $source.revision; sha256 = $source.sha256 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Runtime 'installed.json') -Encoding UTF8
}

function Get-QemuArguments {
    param([string]$Runtime, [ValidateRange(1, 65535)][int]$HttpPort, [ValidateRange(1, 65535)][int]$MonitorPort, [ValidateSet('auto', 'whpx', 'tcg')][string]$Acceleration = 'auto', [switch]$Login, [int]$SerialPort)
    $assets = Join-Path $Runtime 'package/qemu'
    $arguments = @('-L', (Join-Path $assets 'bin'))
    if ($Acceleration -ne 'tcg') { $arguments += @('-accel', 'whpx,kernel-irqchip=off') }
    if ($Acceleration -ne 'whpx') { $arguments += @('-accel', 'tcg') }
    $cmdline = 'console=ttyS0 quiet net.ifnames=0 biosdevname=0 noapic'
    if ($Login) { $cmdline += ' apmyx_login=1' }
    $disk = (Join-Path $Runtime 'session/data.img').Replace('\', '/').Replace(',', ',,')
    $cpu = if ($Acceleration -eq 'tcg') { 'max' } else { 'qemu64-v1' }
    $serial = 'file:' + (Join-Path $Runtime 'service-output.log')
    if ($Login) {
        if ($SerialPort -lt 1 -or $SerialPort -gt 65535) { throw 'A valid local serial port is required for login.' }
        $serial = "tcp:127.0.0.1:$SerialPort,server=on,wait=on"
    }
    $arguments += @('-cpu', $cpu, '-m', '512', '-smp', '2', '-kernel', (Join-Path $assets 'vmlinuz-lite-qemu'), '-initrd', (Join-Path $Runtime 'apmyx-initramfs.cpio.gz'), '-append', $cmdline, '-display', 'none', '-serial', $serial, '-monitor', 'none', '-no-reboot', '-nic', "user,model=e1000,hostfwd=tcp:127.0.0.1:$HttpPort-:12340", '-drive', "file=$disk,format=raw,if=virtio,cache=directsync", '-qmp', "tcp:127.0.0.1:$MonitorPort,server=on,wait=off")
    return $arguments
}

function Get-QemuPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); return $listener.LocalEndpoint.Port } finally { $listener.Stop() }
}

function Assert-QemuPortAvailable {
    param([int]$Port)
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() } catch { throw "Port $Port is already in use. Stop the other wrapper or choose -HttpPort with another port." } finally { $listener.Stop() }
}

function Get-LiteQemuProcess {
    param([string]$Runtime)
    $statePath = Join-Path $Runtime 'process.json'
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $expected = [IO.Path]::GetFullPath((Join-Path $Runtime 'package/qemu/bin/qemu-system-x86_64.exe'))
    if ($process.Path -ne $expected -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $state.started) { throw 'Saved QEMU process identity does not match. No process was stopped.' }
    return [pscustomobject]@{ Process = $process; State = $state }
}

function Invoke-QemuMonitor {
    param([int]$Port, [string]$Command, [hashtable]$Arguments = @{})
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $connection.Wait(3000)) { throw 'QEMU monitor connection timed out.' }
        [void]$connection.GetAwaiter().GetResult()
        $stream = $client.GetStream()
        $stream.ReadTimeout = 5000
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $false, 1024, $true)
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false), 1024, $true)
        try {
            $writer.AutoFlush = $true
            $greeting = $reader.ReadLine() | ConvertFrom-Json
            if (-not $greeting.PSObject.Properties['QMP']) { throw 'QEMU monitor returned an invalid greeting.' }
            foreach ($request in @(@{ execute = 'qmp_capabilities' }, @{ execute = $Command; arguments = $Arguments })) {
                $writer.WriteLine(($request | ConvertTo-Json -Compress))
                do {
                    $line = $reader.ReadLine()
                    if ($null -eq $line) { throw 'QEMU monitor disconnected.' }
                    $response = $line | ConvertFrom-Json
                    if ($response.PSObject.Properties['error']) { throw 'QEMU monitor rejected the shutdown request.' }
                } while (-not $response.PSObject.Properties['return'])
            }
        } finally { $writer.Dispose(); $reader.Dispose() }
    } finally { $client.Dispose() }
}

function Stop-LiteQemu {
    param([string]$Runtime)
    $running = Get-LiteQemuProcess $Runtime
    if ($running -and -not $running.Process.WaitForExit(300)) {
        Write-SetupStatus 'Shutting down the QEMU guest and saving its session...'
        try { Invoke-QemuMonitor -Port $running.State.monitor_port -Command 'human-monitor-command' -Arguments @{ 'command-line' = 'sendkey ctrl-alt-delete' } } catch {
            if (-not $running.Process.HasExited) { throw }
        }
        if (-not $running.Process.WaitForExit(90000)) { throw 'The guest did not shut down cleanly. QEMU was left running to preserve its session disk.' }
    }
    $statePath = Join-Path $Runtime 'process.json'
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
}

function Get-LiteQemuStatus {
    param([int]$HttpPort)
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$HttpPort/status" -TimeoutSec 3
        if ($status.code -ne 0 -or $status.data.regions -isnot [Array] -or @($status.data.regions | Where-Object { $_ -isnot [string] -or -not $_ }).Count) { throw 'Malformed wrapper response.' }
        return [pscustomobject]@{ Ready = $true; Authenticated = @($status.data.regions).Count -gt 0 }
    } catch { return [pscustomobject]@{ Ready = $false; Authenticated = $false } }
}

function Start-LiteQemu {
    param([string]$Runtime, [int]$HttpPort, [string]$Acceleration = 'auto', [switch]$Login)
    Assert-QemuPortAvailable $HttpPort
    do { $monitorPort = Get-QemuPort } while ($monitorPort -eq $HttpPort)
    do { $serialPort = Get-QemuPort } while ($serialPort -eq $monitorPort -or $serialPort -eq $HttpPort)
    $arguments = @(Get-QemuArguments -Runtime $Runtime -HttpPort $HttpPort -MonitorPort $monitorPort -Acceleration $Acceleration -Login:$Login -SerialPort $serialPort)
    $executable = Join-Path $Runtime 'package/qemu/bin/qemu-system-x86_64.exe'
    $commandLine = ($arguments | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' '
    if ($Login) {
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $executable
        $info.Arguments = $commandLine
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [Text.Encoding]::UTF8
        $info.StandardErrorEncoding = [Text.Encoding]::UTF8
        $process = [Diagnostics.Process]::Start($info)
    } else {
        $process = Start-Process -FilePath $executable -ArgumentList $commandLine -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime 'service-host.log') -RedirectStandardError (Join-Path $Runtime 'service-error.log')
    }
    @{ pid = $process.Id; started = $process.StartTime.ToUniversalTime().Ticks.ToString(); http_port = $HttpPort; monitor_port = $monitorPort } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Runtime 'process.json') -Encoding UTF8
    $process | Add-Member -NotePropertyName ApmyxSerialPort -NotePropertyValue $serialPort
    return $process
}

function Open-QemuSerial {
    param($Process)
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) { throw 'QEMU exited before its login console became available.' }
        $client = [Net.Sockets.TcpClient]::new()
        try {
            $connection = $client.ConnectAsync('127.0.0.1', $Process.ApmyxSerialPort)
            if (-not $connection.Wait(500)) { throw 'Serial connection timed out.' }
            [void]$connection.GetAwaiter().GetResult()
            $stream = $client.GetStream()
            $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false), 1024, $true)
            $writer.NewLine = "`n"
            $writer.AutoFlush = $true
            return [pscustomobject]@{ Client = $client; Writer = $writer; Reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $false, 1024, $true) }
        } catch { $client.Dispose(); Start-Sleep -Milliseconds 100 }
    }
    throw 'QEMU login console did not become available.'
}

function Wait-LiteQemu {
    param([string]$Runtime, [int]$HttpPort, [int]$Timeout = 180)
    $deadline = [DateTime]::UtcNow.AddSeconds($Timeout)
    $nextUpdate = [DateTime]::UtcNow
    do {
        if (-not (Get-LiteQemuProcess $Runtime)) { throw 'QEMU exited during startup. Check service-error.log in the QEMU runtime folder, or try -Acceleration tcg if acceleration is unavailable.' }
        $status = Get-LiteQemuStatus $HttpPort
        if ($status.Ready) { return $status }
        if ([DateTime]::UtcNow -ge $nextUpdate) { Write-SetupStatus 'Waiting for the QEMU guest HTTP service...'; $nextUpdate = [DateTime]::UtcNow.AddSeconds(10) }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'QEMU did not become ready in time. Check its runtime logs or retry with -Acceleration tcg.'
}

function Invoke-LiteQemuLogin {
    param([string]$Runtime, [int]$HttpPort, [string]$Acceleration = 'auto')
    $username = Read-Host 'Apple ID email'
    $password = Read-Host 'Apple ID password' -AsSecureString
    $secret = [IntPtr]::Zero
    $process = $null
    $serial = $null
    $complete = $false
    try {
        if (-not $username -or $username -match '[:\r\n]' -or $password.Length -eq 0) { throw 'Enter a nonempty Apple ID and password.' }
        $secret = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secret)
        if ($plainPassword -match '[\r\n]') { throw 'The wrapper cannot accept a password containing a newline.' }
        $process = Start-LiteQemu -Runtime $Runtime -HttpPort $HttpPort -Acceleration $Acceleration -Login
        $hostOutput = $process.StandardOutput.ReadToEndAsync()
        $hostError = $process.StandardError.ReadToEndAsync()
        $serial = Open-QemuSerial $process
        $pending = $serial.Reader.ReadLineAsync()
        $deadline = [DateTime]::UtcNow.AddMinutes(5)
        $sent = $false
        $codeAttempts = 0
        $nextUpdate = [DateTime]::UtcNow
        while ([DateTime]::UtcNow -lt $deadline) {
            if ($null -ne $pending -and $pending.IsCompleted) {
                try { $line = $pending.GetAwaiter().GetResult() } catch {
                    if ($complete -and $process.WaitForExit(10000)) { $pending = $null; break }
                    throw 'The QEMU login console disconnected before authentication completed.'
                }
                if ($null -eq $line) { $pending = $null; continue }
                if (-not $sent -and $line.Contains('[apmyx] credentials-ready')) {
                    $serial.Writer.WriteLine($username)
                    $serial.Writer.WriteLine($plainPassword)
                    $plainPassword = $null
                    $sent = $true
                    Write-SetupStatus 'Signing in to Wrapper Lite...'
                }
                if ($line -match '2FA:\s*true') {
                    if (++$codeAttempts -gt 3) { throw 'Apple verification did not complete. Rerun with -Action Login.' }
                    Write-SetupStatus 'Apple requested a verification code.'
                    $code = Read-Host 'Apple verification code'
                    if ($code -notmatch '^\d{6}$') { throw 'Enter the six-digit Apple verification code.' }
                    $serial.Writer.WriteLine($code)
                    $code = $null
                }
                if ($line.Contains('[apmyx] login-complete')) { $complete = $true }
                if ($line.Contains('[apmyx] login-failed') -or $line.Contains('[apmyx] session-disk-failed')) { throw 'Apple sign-in failed. Check your credentials and account status, then rerun with -Action Login.' }
                $pending = $serial.Reader.ReadLineAsync()
            }
            if ($process.HasExited -and $null -eq $pending) { break }
            if ([DateTime]::UtcNow -ge $nextUpdate) { Write-SetupStatus 'Waiting for the QEMU login guest...'; $nextUpdate = [DateTime]::UtcNow.AddSeconds(15) }
            Start-Sleep -Milliseconds 100
        }
        if (-not $sent -or -not $complete -or -not $process.HasExited -or $process.ExitCode -ne 0) { throw 'Apple sign-in failed or timed out. Rerun with -Action Login.' }
    } finally {
        $plainPassword = $null
        if ($secret -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secret) }
        $password.Dispose()
        if ($process) {
            try { Stop-LiteQemu $Runtime } finally {
                if ($serial) { $serial.Writer.Dispose(); $serial.Reader.Dispose(); $serial.Client.Dispose() }
                $process.Dispose()
            }
        }
    }
}

Export-ModuleMember -Function New-QemuInitramfs, Initialize-LiteQemu, Get-QemuArguments, Get-LiteQemuProcess, Invoke-QemuMonitor, Stop-LiteQemu, Get-LiteQemuStatus, Start-LiteQemu, Wait-LiteQemu, Invoke-LiteQemuLogin
