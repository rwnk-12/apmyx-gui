[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Start', 'Stop', 'Login', 'Status')][string]$Action = 'Setup',
    [ValidateRange(1, 65535)][int]$HttpPort = 12340,
    [ValidateSet('auto', 'whpx', 'tcg')][string]$Acceleration = 'auto',
    [ValidateSet('auto', 'qemu', 'docker')][string]$Backend = 'auto'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$lock = $null

function Save-LiteBackend {
    param([string]$Name)
    [IO.File]::WriteAllText((Join-Path $runtime 'backend.txt'), $Name)
}

function Get-LiteBackend {
    $path = Join-Path $runtime 'backend.txt'
    if (Test-Path -LiteralPath $path) {
        $saved = ([IO.File]::ReadAllText($path)).Trim()
        if ($saved -in @('qemu', 'docker')) { return $saved }
    }
    if (Test-Path -LiteralPath (Join-Path $runtime 'installed.json')) { return 'qemu' }
    if ($Action -ne 'Setup' -and (Find-Docker) -and (Get-LiteContainer)) { return 'docker' }
    return $null
}

function Stop-DockerOnPort {
    if (-not (Find-Docker) -or (Get-DockerResult -Arguments @('info') -TimeoutSeconds 15).ExitCode -ne 0) { return }
    $container = Get-LiteContainer
    if (-not $container -or -not $container.State.Running) { return }
    $binding = $container.HostConfig.PortBindings.PSObject.Properties['12340/tcp']
    if ($binding -and @($binding.Value)[0].HostPort -eq [string]$HttpPort) {
        Write-SetupStatus "Stopping the Docker Wrapper Lite so QEMU can use port $HttpPort. Its login is kept."
        Stop-LiteContainer
    }
}

function Invoke-QemuBackend {
    $running = Get-LiteQemuProcess $runtime
    if ($running -and -not $portGiven) { $script:HttpPort = $running.State.http_port }
    if ($Action -eq 'Stop') { Stop-LiteQemu $runtime; return $null }
    if ($Action -eq 'Status') {
        if (-not $running) { throw 'Wrapper Lite is stopped. Use -Action Start.' }
        return Get-LiteQemuStatus $running.State.http_port
    }
    if ($running -and $Action -ne 'Login') {
        if ($portGiven -and $HttpPort -ne $running.State.http_port) { throw 'Wrapper Lite is already running on another port. Use -Action Stop before changing ports.' }
        return Wait-LiteQemu -Runtime $runtime -HttpPort $running.State.http_port
    }
    if ($running) { Stop-LiteQemu $runtime }
    if ($Action -eq 'Setup') { Initialize-LiteQemu -Runtime $runtime -Scripts $PSScriptRoot }
    Stop-DockerOnPort
    if (-not (Test-Path -LiteralPath (Join-Path $runtime 'installed.json'))) { throw 'Wrapper Lite is not set up yet. Run setup-wrapper-lite-qemu.cmd once.' }
    if ($Action -eq 'Login') { Invoke-LiteQemuLogin -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration }
    $status = Start-LiteQemuReady -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration
    if (-not $status.Authenticated -and $Action -eq 'Setup') {
        Stop-LiteQemu $runtime
        Invoke-LiteQemuLogin -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration
        $status = Start-LiteQemuReady -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration
    }
    return $status
}

function Invoke-DockerBackend {
    param([switch]$AllowInstall)
    if ($Action -in @('Stop', 'Status')) {
        $running = (Find-Docker) -and (Get-DockerResult -Arguments @('info') -TimeoutSeconds 15).ExitCode -eq 0 -and (Get-LiteContainer) -and (Get-LiteContainer).State.Running
        if ($Action -eq 'Stop') { if ($running) { Stop-LiteContainer }; return $null }
        if (-not $running) { throw 'Wrapper Lite is stopped. Use -Action Start.' }
        return Get-LiteDockerStatus $HttpPort
    }
    Initialize-Docker -Runtime $runtime -Install:$AllowInstall
    $image = Import-LiteImage -Runtime $runtime -Scripts $PSScriptRoot
    if ($Action -eq 'Login' -or ($Action -eq 'Setup' -and -not (Test-LiteDockerLogin $image))) {
        Stop-LiteContainer
        Invoke-LiteDockerLogin -Image $image
    }
    Start-LiteContainer -Image $image -HttpPort $HttpPort
    return Wait-LiteContainer -HttpPort $HttpPort
}

try {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This installer targets Windows x64.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Import-Module (Join-Path $PSScriptRoot 'modules/Progress.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'modules/Qemu.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'modules/Docker.psm1') -Force
    $repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $runtime = Join-Path $repository 'backend/wrapper-runtime/wrapper-lite-qemu'
    [IO.Directory]::CreateDirectory($runtime) | Out-Null
    try { $lock = [IO.File]::Open((Join-Path $runtime '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') } catch { throw 'Another Wrapper Lite setup command is running.' }
    Initialize-SetupProgress -Path (Join-Path $runtime 'setup-progress.log')
    $portGiven = $PSBoundParameters.ContainsKey('HttpPort')
    if ($Backend -ne 'auto') {
        $chosen = $Backend
        Save-LiteBackend $chosen
    } else {
        $chosen = Get-LiteBackend
    }
    if (-not $chosen) {
        if ($Action -ne 'Setup') { throw 'Wrapper Lite is not set up yet. Run setup-wrapper-lite-qemu.cmd once.' }
        if ($Acceleration -eq 'tcg' -or (Test-QemuHardwareAcceleration)) {
            $chosen = 'qemu'
        } else {
            Write-SetupStatus 'This PC does not have the Windows Hypervisor Platform that QEMU needs, so Wrapper Lite will run in Docker.'
            Write-SetupStatus ('System: ' + (Get-QemuHostSummary))
            $chosen = 'docker'
        }
        Save-LiteBackend $chosen
    }
    if ($chosen -eq 'qemu') {
        try {
            $status = Invoke-QemuBackend
        } catch {
            if ($Acceleration -ne 'auto' -or $Action -in @('Stop', 'Status') -or $_.Exception.Message -notmatch 'QEMU exited|did not become ready|login console') { throw }
            Write-SetupStatus "QEMU could not start Wrapper Lite on this PC: $($_.Exception.Message)"
            Write-SetupStatus ('System: ' + (Get-QemuHostSummary))
            Write-SetupStatus 'Switching Wrapper Lite to Docker. This only happens once.'
            $chosen = 'docker'
            Save-LiteBackend $chosen
            $status = Invoke-DockerBackend -AllowInstall:($Action -ne 'Start')
        }
    } else {
        $status = Invoke-DockerBackend -AllowInstall:($Action -eq 'Setup')
    }
    if ($Action -eq 'Stop') { Write-SetupStatus 'Wrapper Lite stopped. Your login is saved.'; exit 0 }
    $where = if ($chosen -eq 'docker') { 'in Docker' } else { 'in QEMU' }
    if (-not $status.Ready -or -not $status.Authenticated) {
        if ($Action -eq 'Status') { throw 'Wrapper Lite is running but not signed in. Use -Action Login.' }
        throw 'Wrapper Lite has no signed-in Apple account. Run setup-wrapper-lite-qemu.cmd to sign in.'
    }
    if ($Action -eq 'Status') { Write-SetupStatus "Wrapper Lite is ready $where at http://127.0.0.1:$HttpPort."; exit 0 }
    Write-SetupStatus "Wrapper Lite is ready $where at http://127.0.0.1:$HttpPort. You can close this window."
    Write-Host 'Select AppleMusicDecrypt or Wrapper Lite in GUI Settings > Wrapper.'
    Write-Host 'Use this launcher with -Action Start, Stop, Login, or Status next time.'
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally { if ($lock) { $lock.Dispose() } }
