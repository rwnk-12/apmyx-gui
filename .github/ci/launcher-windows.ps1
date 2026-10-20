Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scripts = Join-Path $PWD 'scripts/wrappers'
Import-Module (Join-Path $scripts 'modules/Progress.psm1') -Force
Import-Module (Join-Path $scripts 'modules/Qemu.psm1') -Force
$runtime = Join-Path $PWD 'backend/wrapper-runtime/wrapper-lite-qemu'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Initialize-SetupProgress -Path (Join-Path $runtime 'setup-progress.log')
Initialize-LiteQemu -Runtime $runtime -Scripts $scripts
Start-LiteQemu -Runtime $runtime -HttpPort 12340 -Acceleration tcg | Out-Null
try {
    $status = Wait-LiteQemu -Runtime $runtime -HttpPort 12340 -Timeout 600
    Write-Host "Wrapper ready=$($status.Ready) authenticated=$($status.Authenticated)"
    if (-not $status.Ready) { throw 'Wrapper HTTP API did not become ready.' }
    if ($status.Authenticated) { throw 'A fresh session disk must not be authenticated.' }
} finally {
    Stop-LiteQemu $runtime
}
if (Get-Process -Name 'qemu-system-x86_64' -ErrorAction SilentlyContinue) { throw 'QEMU is still running after Stop.' }
Write-Host 'Windows launcher test passed.'
