Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Progress.psm1')
Import-Module (Join-Path $PSScriptRoot 'Packages.psm1')

$script:Name = if ($env:APMYX_LITE_DOCKER_NAME) { $env:APMYX_LITE_DOCKER_NAME } else { 'apmyx-wrapper-lite' }
$script:Volume = "$script:Name-data"

function Find-DockerDesktop {
    foreach ($path in @((Join-Path $env:ProgramFiles 'Docker/Docker/Docker Desktop.exe'), (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/Docker Desktop.exe'))) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

function Find-Docker {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $desktop = Find-DockerDesktop
    if ($desktop) {
        $path = Join-Path (Split-Path -Parent $desktop) 'resources/bin/docker.exe'
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

function Get-DockerResult {
    param([string[]]$Arguments, [int]$TimeoutSeconds = 60)
    $result = Invoke-SetupProbe -FilePath (Find-Docker) -Arguments $Arguments -Label "Docker $($Arguments[0])" -TimeoutSeconds $TimeoutSeconds
    $text = if ($result.ExitCode -eq 0) { $result.Stdout } else { $result.Stdout + $result.Stderr }
    return [pscustomobject]@{ ExitCode = $result.ExitCode; Output = @($text -split '\r?\n' | Where-Object { $_.Length -gt 0 }) }
}

function Invoke-Docker {
    param([string[]]$Arguments, [int]$TimeoutSeconds = 60)
    $result = Get-DockerResult -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds
    if ($result.ExitCode -ne 0) { throw "Docker failed: $($result.Output -join [Environment]::NewLine)" }
    return $result.Output
}

function New-DockerProcess {
    param([string[]]$Arguments)
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = Find-Docker
    $info.Arguments = ($Arguments | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $process.Start() | Out-Null
    $writer = [IO.StreamWriter]::new($process.StandardInput.BaseStream, [Text.UTF8Encoding]::new($false))
    $writer.NewLine = "`n"
    $process | Add-Member -NotePropertyName Utf8Input -NotePropertyValue $writer
    return $process
}

function Install-DockerDesktop {
    param([string]$Runtime)
    Write-SetupStatus 'Preparing Docker Desktop with the WSL 2 backend.'
    $wsl = Join-Path $env:SystemRoot 'System32/wsl.exe'
    if (-not (Test-Path -LiteralPath $wsl)) { throw 'WSL is unavailable. Install Windows updates with WSL 2 support, then rerun setup.' }
    $status = Invoke-SetupProbe -FilePath $wsl -Arguments @('--status') -Label 'WSL status check' -TimeoutSeconds 30
    if ($status.ExitCode -ne 0) {
        Write-SetupStatus 'Installing WSL 2. Approve the Windows administrator prompt if shown.'
        $installWsl = Start-Process -FilePath $wsl -ArgumentList @('--install', '--no-distribution', '--web-download') -Verb RunAs -WindowStyle Hidden -PassThru
        $code = Wait-SetupInstaller -Process $installWsl -Label 'WSL installation'
        if ($code -in @(1641, 3010)) { throw 'WSL 2 needs a Windows restart. Restart Windows, then run setup-wrapper-lite-qemu.cmd again.' }
        if ($code -ne 0) { throw "WSL installation failed (exit $code). Finish Windows WSL 2 setup, then run setup again." }
    }
    $installer = Join-Path $Runtime 'DockerDesktopInstaller.exe'
    $trusted = $false
    if (Test-Path -LiteralPath $installer) {
        $signature = Get-SetupSignature -Path $installer
        $trusted = $signature.Status -eq 'Valid' -and $signature.Subject -match 'O="?Docker (Inc\.?|LLC)"?(,|$)'
    }
    if (-not $trusted) {
        $partial = "$installer.partial"
        try {
            Save-SetupDownload -Url 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' -Path $partial -Label 'Docker Desktop installer'
            $signature = Get-SetupSignature -Path $partial
            if ($signature.Status -ne 'Valid' -or $signature.Subject -notmatch 'O="?Docker (Inc\.?|LLC)"?(,|$)') {
                throw "The Docker Desktop installer is not signed by Docker (signature: $($signature.Status)). Installation was stopped."
            }
            Move-Item -LiteralPath $partial -Destination $installer -Force
            Write-SetupStatus 'Docker Desktop installer signature verified.'
        } finally {
            if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        }
    }
    $active = @(Get-Process -Name 'DockerDesktopInstaller', 'Docker Desktop Installer' -ErrorAction SilentlyContinue)
    if ($active.Count) { throw 'A Docker installer is already running. Finish that installation, then run setup again.' }
    $log = Join-Path $env:LOCALAPPDATA 'Docker/install-log.txt'
    Write-SetupStatus "Installing Docker Desktop. Approve the Windows administrator prompt if shown. Installer log: $log"
    $install = Start-Process -FilePath $installer -ArgumentList @('install', '--quiet', '--backend=wsl-2') -Verb RunAs -WindowStyle Hidden -PassThru
    $code = Wait-SetupInstaller -Process $install -Label 'Docker Desktop installation' -LogPath $log
    if ($code -in @(1641, 3010)) { throw 'Docker Desktop needs a Windows restart. Restart Windows, then run setup-wrapper-lite-qemu.cmd again.' }
    if ($code -ne 0) { throw "Docker Desktop installation failed (exit $code). Check $log, then run setup again." }
}

function Initialize-Docker {
    param([string]$Runtime, [switch]$Install)
    if (-not (Find-Docker)) {
        if (-not $Install) { throw 'Docker Desktop is not installed. Run setup-wrapper-lite-qemu.cmd once to install it.' }
        Install-DockerDesktop -Runtime $Runtime
    }
    if (-not (Find-Docker)) { throw 'Docker Desktop installation is incomplete. Restart Windows, finish Docker Desktop setup, then run setup again.' }
    $desktop = Find-DockerDesktop
    $startedDesktop = $false
    $deadline = [DateTime]::UtcNow.AddMinutes(4)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextUpdate = 10
    Write-SetupStatus 'Checking that Docker is running...'
    while ([DateTime]::UtcNow -lt $deadline) {
        $result = Get-DockerResult -Arguments @('info', '--format', '{{.OSType}}') -TimeoutSeconds 15
        if ($result.ExitCode -eq 0) {
            if ($result.Output -notcontains 'linux') { throw 'Docker is using Windows containers. Choose "Switch to Linux containers" in Docker Desktop, then run setup again.' }
            Write-SetupStatus 'Docker is ready.'
            return
        }
        if (-not $startedDesktop) {
            if (-not $desktop) { throw 'Docker is not running. Start Docker, then run setup again.' }
            Write-SetupStatus 'Starting Docker Desktop. Complete its first-run screen if it appears.'
            Start-Process -FilePath $desktop -WindowStyle Hidden
            $startedDesktop = $true
        }
        if ($timer.Elapsed.TotalSeconds -ge $nextUpdate) {
            Write-SetupStatus "Waiting for Docker ($([int]$timer.Elapsed.TotalSeconds)s). Check Docker Desktop for a first-run or restart prompt."
            $nextUpdate += 10
        }
        Start-Sleep -Seconds 3
    }
    throw 'Docker Desktop did not become ready. Finish its WSL 2 setup (restart Windows if asked), then run setup again.'
}

function Get-LiteContainer {
    param([string]$Name = $script:Name)
    $result = Get-DockerResult @('container', 'inspect', $Name)
    if ($result.ExitCode -ne 0) { return $null }
    $container = @($result.Output | ConvertFrom-Json)[0]
    $label = if ($container.Config.Labels) { $container.Config.Labels.PSObject.Properties['io.apmyx.wrapper'] } else { $null }
    if (-not $label -or $label.Value -ne $Name) { throw "A Docker container named '$Name' belongs to something else. Rename or remove it, then run setup again." }
    return $container
}

function Get-LiteContainerOptions {
    param([string]$Name)
    @('--platform', 'linux/amd64', '--name', $Name, '--label', "io.apmyx.wrapper=$Name", '--cap-add', 'SYS_ADMIN', '--cap-add', 'SYS_CHROOT', '--cap-add', 'SYS_PTRACE', '--security-opt', 'apparmor=unconfined', '--mount', "type=volume,source=$($script:Volume),target=/app/rootfs/data")
}

function Get-LiteImageSource {
    param([string]$Scripts)
    $entry = (Get-Content -LiteralPath (Join-Path $Scripts 'qemu/source.json') -Raw | ConvertFrom-Json).PSObject.Properties['docker']
    $source = if ($entry) { $entry.Value } else { $null }
    $fields = if ($source) { $source.PSObject.Properties.Name } else { @() }
    if (-not $source -or @('url', 'sha256', 'size', 'image', 'id', 'manifest' | Where-Object { $_ -notin $fields }).Count -or $source.sha256 -notmatch '^[a-f0-9]{64}$' -or $source.id -notmatch '^sha256:[a-f0-9]{64}$' -or $source.manifest -notmatch '^sha256:[a-f0-9]{64}$') {
        throw 'The pinned Wrapper Lite Docker image is not configured.'
    }
    return $source
}

function Import-LiteImage {
    param([string]$Runtime, [string]$Scripts)
    $source = Get-LiteImageSource $Scripts
    $accepted = @($source.id, $source.manifest)
    $present = Get-DockerResult @('image', 'inspect', '--format', '{{.Id}}', $source.image)
    if ($present.ExitCode -eq 0 -and ($present.Output -join '').Trim() -in $accepted) { return $source.image }
    $archive = Join-Path $Runtime 'wrapper-lite-docker.tar.gz'
    Get-VerifiedDownload -Url $source.url -Path $archive -Sha256 $source.sha256 -ExpectedBytes $source.size
    Write-SetupStatus 'Loading the verified Wrapper Lite image into Docker...'
    Invoke-Docker @('image', 'load', '--input', $archive) -TimeoutSeconds 600 | Out-Null
    $loaded = (Invoke-Docker @('image', 'inspect', '--format', '{{.Id}}', $source.image)) -join ''
    if ($loaded.Trim() -notin $accepted) { throw 'The loaded Docker image does not match the pinned build. Nothing was started.' }
    Remove-Item -LiteralPath $archive -ErrorAction SilentlyContinue
    return $source.image
}

function Test-LiteDockerLogin {
    param([string]$Image)
    $arguments = @('run', '--rm') + @(Get-LiteContainerOptions -Name "$($script:Name)-check") + @('--entrypoint', '/bin/sh', $Image, '-c', 'test -s /app/rootfs/data/mpl_db/kvs.sqlitedb')
    return (Get-DockerResult $arguments -TimeoutSeconds 120).ExitCode -eq 0
}

function Get-LiteDockerStatus {
    param([int]$HttpPort)
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$HttpPort/status" -TimeoutSec 3
        if ($status.code -ne 0 -or $status.data.regions -isnot [Array]) { throw 'Malformed wrapper response.' }
        return [pscustomobject]@{ Ready = $true; Authenticated = @($status.data.regions).Count -gt 0 }
    } catch { return [pscustomobject]@{ Ready = $false; Authenticated = $false } }
}

function Start-LiteContainer {
    param([string]$Image, [int]$HttpPort)
    $existing = Get-LiteContainer
    if ($existing) {
        $binding = $existing.HostConfig.PortBindings.PSObject.Properties['12340/tcp']
        $samePort = $binding -and @($binding.Value)[0].HostPort -eq [string]$HttpPort
        if ($existing.Config.Image -ne $Image -or -not $samePort) {
            Write-SetupStatus 'Updating the Wrapper Lite container. Your login is kept.'
            Invoke-Docker @('rm', '--force', $script:Name) | Out-Null
            $existing = $null
        }
    }
    if ($existing) {
        if (-not $existing.State.Running) { Invoke-Docker @('start', $script:Name) | Out-Null }
        return
    }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $HttpPort)
    try { $listener.Start() } catch { throw "Port $HttpPort is already in use. Stop the other wrapper, then try again." } finally { $listener.Stop() }
    $arguments = @('run', '--detach', '--restart', 'no') + @(Get-LiteContainerOptions -Name $script:Name) + @('--publish', "127.0.0.1:${HttpPort}:12340", $Image)
    Invoke-Docker $arguments | Out-Null
}

function Wait-LiteContainer {
    param([int]$HttpPort, [int]$Timeout = 120)
    $deadline = [DateTime]::UtcNow.AddSeconds($Timeout)
    $nextUpdate = [DateTime]::UtcNow
    do {
        $container = Get-LiteContainer
        if (-not $container -or -not $container.State.Running) {
            $logs = (Get-DockerResult @('logs', '--tail', '5', $script:Name)).Output -join ' | '
            throw "The Wrapper Lite container stopped during startup. $logs"
        }
        $status = Get-LiteDockerStatus $HttpPort
        if ($status.Ready) { return $status }
        if ([DateTime]::UtcNow -ge $nextUpdate) { Write-SetupStatus 'Waiting for Wrapper Lite in Docker...'; $nextUpdate = [DateTime]::UtcNow.AddSeconds(10) }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Wrapper Lite in Docker did not become ready within $Timeout seconds."
}

function Stop-LiteContainer {
    $existing = Get-LiteContainer
    if ($existing -and $existing.State.Running) { Invoke-Docker @('stop', '--time', '5', $script:Name) -TimeoutSeconds 60 | Out-Null }
}

function Invoke-LiteDockerLogin {
    param([string]$Image)
    $loginName = "$($script:Name)-login"
    if (Get-LiteContainer -Name $loginName) { Invoke-Docker @('rm', '--force', $loginName) | Out-Null }
    $username = Read-Host 'Apple ID email'
    $password = Read-Host 'Apple ID password' -AsSecureString
    $secret = [IntPtr]::Zero
    $process = $null
    $completed = $false
    try {
        if (-not $username -or $username -match '[:\r\n]' -or $password.Length -eq 0) { throw 'Enter a nonempty Apple ID and password.' }
        $secret = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secret)
        if ($plain -match '[\r\n]') { throw 'The wrapper cannot accept a password containing a newline.' }
        $arguments = @('run', '--rm', '--interactive') + @(Get-LiteContainerOptions -Name $loginName) + @('--entrypoint', '/bin/sh', $Image, '/app/apmyx-login.sh', 'wrapper-lite')
        $process = New-DockerProcess -Arguments $arguments
        $process.Utf8Input.WriteLine($username)
        $process.Utf8Input.WriteLine($plain)
        $process.Utf8Input.Flush()
        $plain = $null
        Write-SetupStatus 'Signing in to Wrapper Lite...'
        $stdout = $process.StandardOutput.ReadLineAsync()
        $stderr = $process.StandardError.ReadLineAsync()
        $deadline = [DateTime]::UtcNow.AddMinutes(5)
        $askedForCode = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            foreach ($channel in @('stdout', 'stderr')) {
                $pending = Get-Variable -Name $channel -ValueOnly
                if ($null -eq $pending -or -not $pending.IsCompleted) { continue }
                $line = $pending.GetAwaiter().GetResult()
                if ($null -eq $line) { Set-Variable -Name $channel -Value $null; continue }
                if ($line -match '(?i)login complete, exiting') { $completed = $true }
                if (-not $askedForCode -and $line -match '(?i)(2FA:\s*true|Enter.*2FA.*code|Enter.*verification.*code)') {
                    $askedForCode = $true
                    Write-SetupStatus 'Apple requested a verification code.'
                    $code = Read-Host 'Apple verification code'
                    if ($code -notmatch '^\d{6}$') { throw 'Enter the six-digit Apple verification code.' }
                    $writer = New-DockerProcess -Arguments @('exec', '--interactive', $loginName, '/bin/sh', '-c', 'umask 077; cat > /app/rootfs/data/2fa.txt')
                    try {
                        $writer.Utf8Input.WriteLine($code)
                        $writer.Utf8Input.Close()
                        if (-not $writer.WaitForExit(10000) -or $writer.ExitCode -ne 0) { throw 'Could not deliver the verification code to the wrapper.' }
                    } finally {
                        if (-not $writer.HasExited) { $writer.Kill() }
                        $writer.Dispose()
                        $code = $null
                    }
                }
                $reader = if ($channel -eq 'stdout') { $process.StandardOutput } else { $process.StandardError }
                Set-Variable -Name $channel -Value ($reader.ReadLineAsync())
            }
            if ($process.HasExited -and $null -eq $stdout -and $null -eq $stderr) { break }
            Start-Sleep -Milliseconds 100
        }
        if (-not ($process.HasExited -and $process.ExitCode -eq 0 -and $completed)) { throw 'Apple sign-in failed or timed out. Check your Apple ID and password, then run setup again.' }
    } finally {
        $plain = $null
        if ($secret -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secret) }
        $password.Dispose()
        if ($process) {
            try {
                if (Get-LiteContainer -Name $loginName) { Invoke-Docker @('rm', '--force', $loginName) | Out-Null }
            } finally {
                if (-not $process.HasExited) { $process.Kill() }
                $process.Utf8Input.Dispose()
                $process.Dispose()
                Invoke-Docker @('run', '--rm', '--mount', "type=volume,source=$($script:Volume),target=/app/rootfs/data", '--entrypoint', '/bin/sh', $Image, '-c', 'rm -f /app/rootfs/data/2fa.txt') | Out-Null
            }
        }
    }
}

Export-ModuleMember -Function Find-Docker, Get-DockerResult, Invoke-Docker, Initialize-Docker, Get-LiteContainer, Get-LiteImageSource, Import-LiteImage, Test-LiteDockerLogin, Get-LiteDockerStatus, Start-LiteContainer, Wait-LiteContainer, Stop-LiteContainer, Invoke-LiteDockerLogin
