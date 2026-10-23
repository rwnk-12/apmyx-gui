param([switch]$SessionPermissionsOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $repository 'scripts/wrappers'
Import-Module (Join-Path $scripts 'modules/Qemu.psm1') -Force
$module = Get-Module Qemu
$temporary = Join-Path $repository ('build/qemu-tests-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$script:checks = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
    $script:checks++
}

function Assert-Throws {
    param([scriptblock]$Operation, [string]$Pattern)
    $failed = $false
    try { & $Operation | Out-Null } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        $failed = $true
    }
    Assert-True $failed "Expected rejection: $Pattern"
}

try {
    $session = Join-Path $temporary 'session'
    [IO.Directory]::CreateDirectory($session) | Out-Null
    $savedDisk = Join-Path $session 'data.img'
    [IO.File]::WriteAllText($savedDisk, 'existing session fixture')
    & $module { param($Path) Protect-QemuSessionDirectory $Path } $session
    $acl = [IO.DirectoryInfo]::new($session).GetAccessControl([Security.AccessControl.AccessControlSections]::Access)
    Assert-True $acl.AreAccessRulesProtected 'Session access does not inherit permissions from the checkout'
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    $allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
    Assert-True (@($rules | Where-Object { $_.IdentityReference.Value -notin $allowed -or $_.AccessControlType -ne 'Allow' }).Count -eq 0) 'Limit session access to the current user and SYSTEM'
    foreach ($sid in $allowed) {
        Assert-True (@($rules | Where-Object { $_.IdentityReference.Value -eq $sid -and $_.FileSystemRights -eq 'FullControl' }).Count -eq 1) 'Preserve full access for the session owner and SYSTEM'
    }
    & $module { param($Path) Protect-QemuSessionDirectory $Path } $session
    Assert-True ([IO.File]::ReadAllText($savedDisk) -eq 'existing session fixture') 'Repeated setup preserves the saved session disk'
    if ($SessionPermissionsOnly) { Write-Output "$script:checks session permission checks passed."; return }
    foreach ($file in Get-ChildItem -Path $scripts -Recurse -File -Include *.ps1, *.psm1) {
        $tokens = $null
        $parseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
        Assert-True ($parseErrors.Count -eq 0) "PowerShell syntax: $($file.Name)"
    }
    $source = Get-Content (Join-Path $scripts 'qemu/source.json') -Raw | ConvertFrom-Json
    Assert-True ($source.sha256 -match '^[a-f0-9]{64}$' -and $source.size -gt 0) 'Artifact identity is pinned'
    $arguments = @(Get-QemuArguments -Runtime $temporary -HttpPort 23450 -MonitorPort 23451 -Acceleration tcg)
    Assert-True ($arguments -contains 'user,model=e1000,hostfwd=tcp:127.0.0.1:23450-:12340') 'Expose the wrapper only on loopback'
    Assert-True ($arguments -contains 'tcp:127.0.0.1:23451,server=on,wait=off') 'Expose QMP only on loopback'
    Assert-True ($arguments -contains 'max' -and $arguments -notcontains 'whpx,kernel-irqchip=off') 'Explicit TCG does not need Windows virtualization'
    Assert-True (($arguments -join ' ') -notmatch 'apmyx_login=1|--login|password') 'Service launch has no credential parameters'
    $loginArguments = @(Get-QemuArguments -Runtime $temporary -HttpPort 23450 -MonitorPort 23451 -SerialPort 23452 -Login)
    Assert-True (($loginArguments -join ' ') -match 'apmyx_login=1') 'Login selects the serial-input guest mode'
    Assert-True ($loginArguments -contains 'whpx,kernel-irqchip=off' -and $loginArguments -notcontains 'tcg') 'Automatic acceleration never falls back to slow software emulation'
    Assert-True ($loginArguments -contains 'tcp:127.0.0.1:23452,server=on,wait=on') 'Login serial transport is local and waits for the host'
    $currentProcess = Get-Process -Id $PID
    @{ pid = $PID; started = $currentProcess.StartTime.ToUniversalTime().Ticks.ToString(); monitor_port = 23451; http_port = 23450 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $temporary 'process.json')
    Assert-Throws { Stop-LiteQemu $temporary } 'identity does not match'
    Assert-True (-not $currentProcess.HasExited) 'Never stop a process from a stale or foreign PID record'
    Remove-Item -LiteralPath (Join-Path $temporary 'process.json')
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        Assert-Throws { & $module { param($Port) Assert-QemuPortAvailable $Port } $listener.LocalEndpoint.Port } 'already in use'
    } finally { $listener.Stop() }
    $original = Join-Path $temporary 'original.gz'
    $overlay = Join-Path $temporary 'overlay.gz'
    [IO.File]::WriteAllBytes($original, [byte[]](1, 2, 3))
    New-QemuInitramfs -Original $original -InitScript (Join-Path $scripts 'qemu/init') -Destination $overlay
    $stream = [IO.File]::OpenRead($overlay)
    try {
        $stream.Position = 3
        $gzip = [IO.Compression.GZipStream]::new($stream, [IO.Compression.CompressionMode]::Decompress)
        try {
            $cpio = [IO.MemoryStream]::new()
            try {
                $gzip.CopyTo($cpio)
                $bytes = $cpio.ToArray()
                Assert-True ([Text.Encoding]::ASCII.GetString($bytes, 0, 6) -eq '070701') 'Build a Linux newc initramfs overlay'
                Assert-True ([Text.Encoding]::ASCII.GetString($bytes, 14, 8) -eq '000081ed') 'Guest init is executable'
                $initText = [Text.Encoding]::UTF8.GetString($bytes)
                Assert-True ($initText.Contains('credentials-ready') -and $initText.Contains('stty -echo')) 'Disable serial echo before accepting credentials'
                Assert-True (-not $initText.Contains("`r")) 'Guest shell uses LF line endings'
                Assert-True (-not $initText.Contains('lite_args_b64=') -and -not $initText.Contains('fw_cfg')) 'Credentials never enter kernel arguments or guest files'
                Assert-True ($initText.Contains('sync') -and $initText.Contains('umount /data')) 'Flush session storage before shutdown'
            } finally { $cpio.Dispose() }
        } finally { $gzip.Dispose() }
    } finally { $stream.Dispose() }
    & $module {
        $script:responses = @('person@example.com', '123456')
        $script:fakePassword = 'fake secret with spaces'
        $script:loginLines = "[apmyx] credentials-ready`n2FA: true`n[apmyx] login-complete`n"
        $script:exitCode = 0
        $script:stops = 0
        function script:Read-Host {
            param($Prompt, [switch]$AsSecureString)
            if ($AsSecureString) { return ConvertTo-SecureString $script:fakePassword -AsPlainText -Force }
            $result = $script:responses[0]
            $script:responses = @($script:responses | Select-Object -Skip 1)
            return $result
        }
        function script:Start-LiteQemu {
            $script:sentInput = [IO.MemoryStream]::new()
            $stdout = [IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($script:loginLines))
            $stderr = [IO.MemoryStream]::new()
            $process = [pscustomobject]@{
                StandardInput = [pscustomobject]@{ BaseStream = $script:sentInput }
                StandardOutput = [IO.StreamReader]::new($stdout)
                StandardError = [IO.StreamReader]::new($stderr)
                HasExited = $true
                ExitCode = $script:exitCode
            }
            $process | Add-Member ScriptMethod Dispose { $this.StandardOutput.Dispose(); $this.StandardError.Dispose() }
            return $process
        }
        function script:Open-QemuSerial {
            $reader = [IO.StreamReader]::new([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($script:loginLines)))
            $writer = [IO.StreamWriter]::new($script:sentInput, [Text.UTF8Encoding]::new($false))
            $writer.NewLine = "`n"
            $writer.AutoFlush = $true
            return [pscustomobject]@{ Reader = $reader; Writer = $writer; Client = [IO.MemoryStream]::new() }
        }
        function script:Stop-LiteQemu { $script:stops++ }
    }
    Invoke-LiteQemuLogin -Runtime $temporary -HttpPort 23450
    $sent = & $module { [Text.Encoding]::UTF8.GetString($script:sentInput.ToArray()) }
    Assert-True ($sent -eq "person@example.com`nfake secret with spaces`n123456`n") 'Credentials and 2FA use the UTF-8 serial stream with LF delimiters'
    Assert-True ((& $module { $script:stops }) -eq 1) 'Clean up the login guest'
    & $module { $script:responses = @('person@example.com'); $script:loginLines = "[apmyx] credentials-ready`n" }
    Assert-Throws { Invoke-LiteQemuLogin -Runtime $temporary -HttpPort 23450 } 'sign-in failed'
    & $module { $script:responses = @('person@example.com'); $script:loginLines = "[apmyx] login-complete`n"; $script:exitCode = 1 }
    Assert-Throws { Invoke-LiteQemuLogin -Runtime $temporary -HttpPort 23450 } 'sign-in failed'
    & $module { $script:responses = @('person@example.com', 'invalid'); $script:exitCode = 0; $script:loginLines = "[apmyx] credentials-ready`n2FA: true`n" }
    Assert-Throws { Invoke-LiteQemuLogin -Runtime $temporary -HttpPort 23450 } 'six-digit'
    & $module { $script:responses = @('person@example.com'); $script:fakePassword = "bad`npassword" }
    Assert-Throws { Invoke-LiteQemuLogin -Runtime $temporary -HttpPort 23450 } 'newline'
    & $module { function script:Invoke-RestMethod { '{"code":0,"data":{"regions":["us"]}}' | ConvertFrom-Json } }
    Assert-True (Get-LiteQemuStatus 23450).Authenticated 'Recognize an authenticated wrapper'
    & $module { function script:Invoke-RestMethod { '{"code":0,"data":{"regions":[]}}' | ConvertFrom-Json } }
    Assert-True (-not (Get-LiteQemuStatus 23450).Authenticated) 'Recognize an unauthenticated wrapper'
    & $module { function script:Invoke-RestMethod { @{ invalid = $true } } }
    Assert-True (-not (Get-LiteQemuStatus 23450).Ready) 'Reject incompatible status output'
    & $module { function script:Invoke-RestMethod { '{"code":0,"data":{"regions":"us"}}' | ConvertFrom-Json } }
    Assert-True (-not (Get-LiteQemuStatus 23450).Ready) 'Reject malformed account regions'
    & $module { function script:Invoke-RestMethod { throw 'unavailable' } }
    Assert-True (-not (Get-LiteQemuStatus 23450).Ready) 'Handle unavailable wrapper'

    $failureRuntime = Join-Path $temporary 'failure'
    [IO.Directory]::CreateDirectory($failureRuntime) | Out-Null
    [IO.File]::WriteAllLines((Join-Path $failureRuntime 'service-error.log'), @(
        "C:\apmyx\qemu-system-x86_64.exe: warning: host doesn't support requested feature: CPUID[eax=80000001h].ECX.svm [bit 2]",
        'C:\apmyx\qemu-system-x86_64.exe: WHPX: Failed to emulate MMIO access with EmulatorReturnStatus: 2'))
    $exited = [pscustomobject]@{ HasExited = $true; ExitCode = -1073741515 }
    $detail = Get-QemuFailureDetail -Runtime $failureRuntime -Process $exited
    Assert-True ($detail -match '0xC0000135' -and $detail -match 'missing') 'Explain Windows exit codes in plain words'
    Assert-True ($detail -match 'Failed to emulate MMIO access' -and $detail -notmatch 'svm') 'Show the real QEMU error and hide harmless CPU warnings'
    Assert-True ((Get-QemuFailureDetail -Runtime $failureRuntime -Process ([pscustomobject]@{ HasExited = $true; ExitCode = -1073740760 })) -match 'Smart App Control') 'Recognize Application Control blocks'

    Assert-True ((Test-QemuHardwareAcceleration) -is [bool]) 'Report whether QEMU hardware acceleration is possible'
    & $module {
        $script:boots = [Collections.Generic.List[string]]::new()
        $script:removed = 0
        function script:Start-LiteQemu { param($Runtime, $HttpPort, $Acceleration, [switch]$Login) $script:boots.Add($Acceleration); [pscustomobject]@{ HasExited = $true; ExitCode = -1073741819 } }
        function script:Wait-LiteQemu { param($Runtime, $HttpPort, $Timeout, $Process) throw 'QEMU exited during startup (exit code 0xC0000005, QEMU crashed).' }
        function script:Remove-LiteQemu { param($Runtime, $Process) $script:removed++ }
    }
    Assert-Throws { Start-LiteQemuReady -Runtime $failureRuntime -HttpPort 23450 -Acceleration auto } 'QEMU exited during startup .*crashed'
    Assert-True (((& $module { $script:boots }) -join ',') -eq 'auto' -and (& $module { $script:removed }) -eq 1) 'A failed boot is cleaned up and never retried in software mode'

    Import-Module (Join-Path $scripts 'modules/Docker.psm1') -Force
    $docker = Get-Module Docker
    $fakeScripts = Join-Path $temporary 'fake-scripts'
    [IO.Directory]::CreateDirectory((Join-Path $fakeScripts 'qemu')) | Out-Null
    '{"url":"https://example.invalid/q.zip"}' | Set-Content (Join-Path $fakeScripts 'qemu/source.json')
    Assert-Throws { Get-LiteImageSource $fakeScripts } 'not configured'
    $withoutManifest = '{"docker":{"url":"https://example.invalid/i.tar.gz","sha256":"' + ('a' * 64) + '","size":1,"image":"apmyx/wrapper-lite:test","id":"sha256:' + ('b' * 64) + '"}}'
    $withoutManifest | Set-Content (Join-Path $fakeScripts 'qemu/source.json')
    Assert-Throws { Get-LiteImageSource $fakeScripts } 'not configured'
    $pinned = '{"docker":{"url":"https://example.invalid/i.tar.gz","sha256":"' + ('a' * 64) + '","size":1,"image":"apmyx/wrapper-lite:test","id":"sha256:' + ('b' * 64) + '","manifest":"sha256:' + ('c' * 64) + '"}}'
    $pinned | Set-Content (Join-Path $fakeScripts 'qemu/source.json')
    Assert-True ((Get-LiteImageSource $fakeScripts).image -eq 'apmyx/wrapper-lite:test') 'Docker image identity is pinned by hash and image ID'

    & $docker {
        $script:calls = [Collections.Generic.List[string]]::new()
        $script:fakeContainer = $null
        function script:Get-LiteContainer { param($Name) $script:fakeContainer }
        function script:Invoke-Docker { param([string[]]$Arguments, $TimeoutSeconds) $script:calls.Add($Arguments -join ' '); @() }
        function script:Write-SetupStatus { param([string]$Message) }
    }
    $binding = { param($Port) [pscustomobject]@{ '12340/tcp' = @([pscustomobject]@{ HostPort = [string]$Port }) } }
    & $docker { param($b) $script:fakeContainer = [pscustomobject]@{ Config = [pscustomobject]@{ Image = 'apmyx/wrapper-lite:test' }; HostConfig = [pscustomobject]@{ PortBindings = (& $b 23450) }; State = [pscustomobject]@{ Running = $false } } } $binding
    Start-LiteContainer -Image 'apmyx/wrapper-lite:test' -HttpPort 23450
    Assert-True ((& $docker { $script:calls -join ';' }) -eq 'start apmyx-wrapper-lite') 'Reuse a stopped container that already matches'
    & $docker { param($b) $script:calls.Clear(); $script:fakeContainer = [pscustomobject]@{ Config = [pscustomobject]@{ Image = 'apmyx/wrapper-lite:old' }; HostConfig = [pscustomobject]@{ PortBindings = (& $b 23450) }; State = [pscustomobject]@{ Running = $true } } } $binding
    Start-LiteContainer -Image 'apmyx/wrapper-lite:test' -HttpPort 23450
    $calls = & $docker { @($script:calls) }
    Assert-True ($calls[0] -eq 'rm --force apmyx-wrapper-lite') 'Replace a container built from an older image'
    Assert-True ($calls[1] -match 'type=volume,source=apmyx-wrapper-lite-data,target=/app/rootfs/data' -and $calls[1] -match '--publish 127.0.0.1:23450:12340' -and $calls[1] -match 'apmyx/wrapper-lite:test$') 'Keep the login volume and publish only on loopback'
    & $docker { param($b) $script:calls.Clear(); $script:fakeContainer = [pscustomobject]@{ Config = [pscustomobject]@{ Image = 'apmyx/wrapper-lite:test' }; HostConfig = [pscustomobject]@{ PortBindings = (& $b 34560) }; State = [pscustomobject]@{ Running = $false } } } $binding
    Start-LiteContainer -Image 'apmyx/wrapper-lite:test' -HttpPort 23450
    Assert-True ((& $docker { $script:calls[0] }) -eq 'rm --force apmyx-wrapper-lite') 'Recreate the container when the port changes'
    Write-Output "$script:checks QEMU setup checks passed."
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    $buildRoot = [IO.Path]::GetFullPath((Join-Path $repository 'build')) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($buildRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Test cleanup path escaped the build directory.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
