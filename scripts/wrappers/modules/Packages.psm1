Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Import-Module (Join-Path $PSScriptRoot 'Progress.psm1')

function Get-VerifiedDownload {
    param([string]$Url, [string]$Path, [string]$Sha256, [long]$ExpectedBytes = -1)
    if ((Test-Path -LiteralPath $Path) -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Sha256) {
        Write-SetupStatus 'Using the cached wrapper package. SHA-256 verified.'
        return
    }
    $partial = "$Path.partial"
    try {
        Save-SetupDownload -Url $Url -Path $partial -Label 'Wrapper package' -ExpectedBytes $ExpectedBytes
        Write-SetupStatus 'Verifying wrapper package SHA-256...'
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Sha256) {
            throw 'Download checksum mismatch. No downloaded code was run. The pinned package may have changed.'
        }
        Move-Item -LiteralPath $partial -Destination $Path -Force
        Write-SetupStatus 'Wrapper package checksum verified.'
    } finally {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    }
}

function Expand-SafeArchive {
    param([string]$Path, [string]$Destination)
    $root = [IO.Path]::GetFullPath($Destination).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $zip = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        foreach ($entry in $zip.Entries) {
            $relative = $entry.FullName.Replace('/', [IO.Path]::DirectorySeparatorChar)
            $target = [IO.Path]::GetFullPath((Join-Path $root $relative))
            if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -or $relative.Contains(':')) {
                throw 'Archive contains an unsafe path.'
            }
            if (($entry.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000) {
                throw 'The archive contains a symbolic link and was not extracted.'
            }
        }
        foreach ($entry in $zip.Entries) {
            $target = Join-Path $root $entry.FullName
            if ($entry.FullName.EndsWith('/')) {
                [IO.Directory]::CreateDirectory($target) | Out-Null
            } else {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
            }
        }
    } finally {
        $zip.Dispose()
    }
}

Export-ModuleMember -Function Get-VerifiedDownload, Expand-SafeArchive
