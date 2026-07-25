$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$bundle = if ($env:DHAD_WINDOWS_BUNDLE) { $env:DHAD_WINDOWS_BUNDLE.ToLowerInvariant() } else { '' }
if ($bundle -notin @('nsis', 'msi')) {
    throw "DHAD_WINDOWS_BUNDLE must be 'nsis' or 'msi', got '$bundle'."
}

$extension = if ($bundle -eq 'msi') { '.msi' } else { '.exe' }
$candidates = Get-ChildItem -Path (Join-Path $root 'target') -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Extension.ToLowerInvariant() -eq $extension -and
        $_.FullName -match "[\\/]bundle[\\/]$bundle[\\/]"
    } |
    Sort-Object LastWriteTimeUtc -Descending

if (-not $candidates) {
    throw "No generated $bundle installer was found under target/*/release/bundle/$bundle."
}
$installer = $candidates[0]
if ($installer.Length -lt 1MB) {
    throw "Generated installer is unexpectedly small: $($installer.FullName) ($($installer.Length) bytes)."
}
Write-Host "Verifying $bundle installer: $($installer.FullName)"
Write-Host "Installer size: $($installer.Length) bytes"

if ($bundle -eq 'nsis') {
    $stream = [System.IO.File]::OpenRead($installer.FullName)
    try {
        $first = $stream.ReadByte()
        $second = $stream.ReadByte()
    }
    finally {
        $stream.Dispose()
    }
    if ($first -ne 0x4D -or $second -ne 0x5A) {
        throw 'NSIS installer does not have a valid PE MZ header.'
    }

    $installRoot = Join-Path $env:RUNNER_TEMP 'dhad-nsis-smoke'
    Remove-Item -LiteralPath $installRoot -Recurse -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $installer.FullName -ArgumentList @('/S', "/D=$installRoot") -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "NSIS silent installation failed with exit code $($process.ExitCode)."
    }
    $app = Get-ChildItem -Path $installRoot -Filter 'dhad-desktop.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $app) {
        throw 'NSIS installation completed but dhad-desktop.exe was not installed.'
    }
    $uninstaller = Get-ChildItem -Path $installRoot -Filter 'uninstall*.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($uninstaller) {
        $uninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList '/S' -Wait -PassThru
        if ($uninstall.ExitCode -ne 0) {
            throw "NSIS silent uninstall failed with exit code $($uninstall.ExitCode)."
        }
    }
    Remove-Item -LiteralPath $installRoot -Recurse -Force -ErrorAction SilentlyContinue
}
else {
    $adminRoot = Join-Path $env:RUNNER_TEMP 'dhad-msi-admin-image'
    Remove-Item -LiteralPath $adminRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $adminRoot | Out-Null
    $arguments = @('/a', "`"$($installer.FullName)`"", '/qn', "TARGETDIR=`"$adminRoot`"")
    $process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "MSI administrative extraction failed with exit code $($process.ExitCode)."
    }
    $app = Get-ChildItem -Path $adminRoot -Filter 'dhad-desktop.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $app) {
        throw 'MSI database opened successfully but the administrative image contains no dhad-desktop.exe.'
    }
    Remove-Item -LiteralPath $adminRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$signature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
Write-Host "Authenticode status: $($signature.Status)"
if ($env:DHAD_REQUIRE_WINDOWS_SIGNED -eq '1' -and $signature.Status -ne 'Valid') {
    throw "A valid Authenticode signature is required, got $($signature.Status)."
}
Write-Host "Windows $bundle installer verification: PASS"
