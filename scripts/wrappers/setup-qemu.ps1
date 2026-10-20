[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Start', 'Stop', 'Login', 'Status')][string]$Action = 'Setup',
    [ValidateRange(1, 65535)][int]$HttpPort = 12340,
    [ValidateSet('auto', 'whpx', 'tcg')][string]$Acceleration = 'auto'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$lock = $null
try {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This QEMU installer targets Windows x64.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Import-Module (Join-Path $PSScriptRoot 'modules/Progress.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'modules/Qemu.psm1') -Force
    $repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $runtime = Join-Path $repository 'backend/wrapper-runtime/wrapper-lite-qemu'
    [IO.Directory]::CreateDirectory($runtime) | Out-Null
    try { $lock = [IO.File]::Open((Join-Path $runtime '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') } catch { throw 'Another Wrapper Lite QEMU setup command is running.' }
    Initialize-SetupProgress -Path (Join-Path $runtime 'setup-progress.log')
    $running = Get-LiteQemuProcess $runtime
    if ($running -and -not $PSBoundParameters.ContainsKey('HttpPort')) { $HttpPort = $running.State.http_port }
    if ($Action -eq 'Stop') { Stop-LiteQemu $runtime; Write-SetupStatus 'Wrapper Lite QEMU stopped. Your login is saved.'; exit 0 }
    if ($Action -eq 'Status') {
        if (-not $running) { throw 'Wrapper Lite QEMU is stopped. Use -Action Start.' }
        $status = Get-LiteQemuStatus $running.State.http_port
        if (-not $status.Ready -or -not $status.Authenticated) { throw 'Wrapper Lite QEMU is not authenticated and ready. Use -Action Login.' }
        Write-SetupStatus "Wrapper Lite QEMU is ready at http://127.0.0.1:$($running.State.http_port)."
        exit 0
    }
    if ($running -and $Action -ne 'Login') {
        if ($PSBoundParameters.ContainsKey('HttpPort') -and $HttpPort -ne $running.State.http_port) { throw 'QEMU is already running on another port. Use -Action Stop before changing ports.' }
        $HttpPort = $running.State.http_port
        $status = Wait-LiteQemu -Runtime $runtime -HttpPort $HttpPort
    } else {
        if ($running) { Stop-LiteQemu $runtime }
        if ($Action -eq 'Setup') { Initialize-LiteQemu -Runtime $runtime -Scripts $PSScriptRoot }
        if (-not (Test-Path -LiteralPath (Join-Path $runtime 'installed.json'))) { throw 'Run setup-wrapper-lite-qemu.cmd without -Action to install the package first.' }
        if ($Action -eq 'Login') { Invoke-LiteQemuLogin -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration }
        Start-LiteQemu -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration | Out-Null
        $status = Wait-LiteQemu -Runtime $runtime -HttpPort $HttpPort
    }
    if (-not $status.Authenticated -and $Action -eq 'Setup') {
        Stop-LiteQemu $runtime
        Invoke-LiteQemuLogin -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration
        Start-LiteQemu -Runtime $runtime -HttpPort $HttpPort -Acceleration $Acceleration | Out-Null
        $status = Wait-LiteQemu -Runtime $runtime -HttpPort $HttpPort
    }
    if (-not $status.Authenticated) { throw 'Wrapper Lite has no authenticated session. Use -Action Login.' }
    Write-SetupStatus "Wrapper Lite QEMU is ready at http://127.0.0.1:$HttpPort. You can close this window."
    Write-Host 'Select AppleMusicDecrypt or Wrapper Lite in GUI Settings > Wrapper.'
    Write-Host 'Use this launcher with -Action Start, Stop, Login, or Status next time.'
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally { if ($lock) { $lock.Dispose() } }
