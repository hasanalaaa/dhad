$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$baseConfigPath = Join-Path $root 'src-tauri/tauri.conf.json'
$windowsConfigPath = Join-Path $root 'src-tauri/tauri.windows.conf.json'
$config = Get-Content -LiteralPath $baseConfigPath -Raw | ConvertFrom-Json
$windowsConfig = if (Test-Path -LiteralPath $windowsConfigPath -PathType Leaf) {
    Get-Content -LiteralPath $windowsConfigPath -Raw | ConvertFrom-Json
}
else {
    $null
}

function Get-OptionalPropertyValue([object]$Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    $property.Value
}

$productName = [string]$(
    if ($null -ne $windowsConfig -and -not [string]::IsNullOrWhiteSpace([string](Get-OptionalPropertyValue $windowsConfig 'productName'))) {
        Get-OptionalPropertyValue $windowsConfig 'productName'
    }
    else {
        Get-OptionalPropertyValue $config 'productName'
    }
)
$productVersion = [string](Get-OptionalPropertyValue $config 'version')
$mainBinary = [string](Get-OptionalPropertyValue $config 'mainBinaryName')
$bundleConfig = Get-OptionalPropertyValue $config 'bundle'
$publisher = [string](Get-OptionalPropertyValue $bundleConfig 'publisher')

if ([string]::IsNullOrWhiteSpace($productName) -or [string]::IsNullOrWhiteSpace($productVersion) -or [string]::IsNullOrWhiteSpace($mainBinary)) {
    throw 'Effective Windows productName, version, and mainBinaryName are required for verification.'
}
$expectedExe = "$mainBinary.exe"

function Test-PeHeader([string]$Path, [string]$Label) {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $first = $stream.ReadByte()
        $second = $stream.ReadByte()
    }
    finally {
        $stream.Dispose()
    }
    if ($first -ne 0x4D -or $second -ne 0x5A) {
        throw "$Label does not have a valid PE MZ header: $Path"
    }
}

function Test-DhadUninstallEntry([object]$Entry) {
    $displayName = [string](Get-OptionalPropertyValue $Entry 'DisplayName')
    if ([string]::IsNullOrWhiteSpace($displayName) -or $displayName -ne $productName) {
        return $false
    }
    $displayVersion = [string](Get-OptionalPropertyValue $Entry 'DisplayVersion')
    [string]::IsNullOrWhiteSpace($displayVersion) -or $displayVersion -eq $productVersion
}

function Get-DhadUninstallEntries {
    $paths = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $entries = foreach ($path in $paths) {
        Get-ItemProperty -Path $path -ErrorAction SilentlyContinue |
            Where-Object { Test-DhadUninstallEntry $_ }
    }
    @($entries)
}

function Add-RootCandidate([System.Collections.Generic.List[string]]$Roots, [object]$Value) {
    if ($null -eq $Value) { return }
    $candidate = ([string]$Value).Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($candidate)) { return }
    if ($candidate -match '^(?<exe>.+?\.exe)(?:\s+.*)?$') {
        $candidate = Split-Path -Parent $Matches.exe.Trim('"')
    }
    if (-not [string]::IsNullOrWhiteSpace($candidate) -and -not $Roots.Contains($candidate)) {
        $Roots.Add($candidate)
    }
}

function Resolve-Executable([object[]]$Entries) {
    $roots = [System.Collections.Generic.List[string]]::new()
    foreach ($entry in $Entries) {
        Add-RootCandidate $roots (Get-OptionalPropertyValue $entry 'InstallLocation')
        Add-RootCandidate $roots (Get-OptionalPropertyValue $entry 'UninstallString')
        Add-RootCandidate $roots (Get-OptionalPropertyValue $entry 'QuietUninstallString')
    }

    if (-not [string]::IsNullOrWhiteSpace($publisher)) {
        foreach ($registryPath in @(
            "HKCU:\Software\$publisher\$productName",
            "HKLM:\Software\$publisher\$productName"
        )) {
            try {
                $defaultValue = (Get-Item -LiteralPath $registryPath -ErrorAction Stop).GetValue('')
                Add-RootCandidate $roots $defaultValue
            }
            catch { }
        }
    }

    foreach ($known in @(
        (Join-Path $env:LOCALAPPDATA $productName),
        (Join-Path $env:ProgramFiles $productName),
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} $productName } else { $null })
    )) {
        Add-RootCandidate $roots $known
    }

    foreach ($candidateRoot in $roots) {
        $direct = Join-Path $candidateRoot $expectedExe
        if (Test-Path -LiteralPath $direct -PathType Leaf) {
            return [pscustomobject]@{ App = Get-Item -LiteralPath $direct; Roots = $roots }
        }
        if (Test-Path -LiteralPath $candidateRoot -PathType Container) {
            $nested = Get-ChildItem -LiteralPath $candidateRoot -Filter $expectedExe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($nested) {
                return [pscustomobject]@{ App = $nested; Roots = $roots }
            }
        }
    }
    [pscustomobject]@{ App = $null; Roots = $roots }
}

function Resolve-Uninstaller([object[]]$Entries, [string]$InstallRoot) {
    foreach ($entry in $Entries) {
        foreach ($name in @('QuietUninstallString', 'UninstallString')) {
            $value = Get-OptionalPropertyValue $entry $name
            if ([string]::IsNullOrWhiteSpace([string]$value)) { continue }
            $raw = ([string]$value).Trim()
            if ($raw -match '^"(?<exe>[^"]+\.exe)"\s*(?<args>.*)$') {
                if (Test-Path -LiteralPath $Matches.exe -PathType Leaf) {
                    return [pscustomobject]@{ Exe = $Matches.exe; Args = $Matches.args }
                }
            }
            elseif ($raw -match '^(?<exe>.+?\.exe)(?:\s+(?<args>.*))?$') {
                $exe = $Matches.exe.Trim('"')
                if (Test-Path -LiteralPath $exe -PathType Leaf) {
                    return [pscustomobject]@{ Exe = $exe; Args = [string]$Matches.args }
                }
            }
        }
    }
    $fallback = Join-Path $InstallRoot 'uninstall.exe'
    if (Test-Path -LiteralPath $fallback -PathType Leaf) {
        return [pscustomobject]@{ Exe = $fallback; Args = '' }
    }
    $null
}

if ($env:DHAD_WINDOWS_VERIFIER_LIBRARY_ONLY -eq '1') {
    Write-Host 'Windows installer verifier library loaded: PASS'
    return
}

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
Write-Host "Effective Windows product name: $productName"
Write-Host "Verifying $bundle installer: $($installer.FullName)"
Write-Host "Installer size: $($installer.Length) bytes"

if ($bundle -eq 'nsis') {
    Test-PeHeader $installer.FullName 'NSIS installer'

    $process = Start-Process -FilePath $installer.FullName -ArgumentList '/S' -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "NSIS silent installation failed with exit code $($process.ExitCode)."
    }

    $entries = @()
    $resolved = $null
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $entries = Get-DhadUninstallEntries
        $resolved = Resolve-Executable $entries
        if ($resolved.App) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $resolved.App) {
        Write-Host 'NSIS uninstall registry entries:'
        $entries | Select-Object DisplayName, DisplayVersion, InstallLocation, UninstallString, QuietUninstallString | Format-List | Out-String | Write-Host
        Write-Host "Candidate installation roots: $($resolved.Roots -join '; ')"
        $diagnosticRoots = @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $matches = foreach ($diagnosticRoot in $diagnosticRoots) {
            Get-ChildItem -LiteralPath $diagnosticRoot -Filter $expectedExe -Recurse -File -Depth 4 -ErrorAction SilentlyContinue
        }
        Write-Host "Discovered matching executables: $((@($matches).FullName) -join '; ')"
        throw "NSIS installation completed but $expectedExe could not be resolved from registry or standard install roots."
    }

    $app = $resolved.App
    Write-Host "Installed executable: $($app.FullName)"
    Write-Host "Installed executable size: $($app.Length) bytes"
    if ($app.Length -lt 1MB) {
        throw "Installed executable is unexpectedly small: $($app.FullName)"
    }
    Test-PeHeader $app.FullName 'Installed application'

    $desktopPaths = @(
        [Environment]::GetFolderPath('Desktop'),
        [Environment]::GetFolderPath('CommonDesktopDirectory')
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    $shortcut = foreach ($desktopPath in $desktopPaths) {
        $candidate = Join-Path $desktopPath "$productName.lnk"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { Get-Item -LiteralPath $candidate }
    }
    if (-not $shortcut) {
        throw "NSIS installed $expectedExe but did not create the native Tauri desktop shortcut '$productName.lnk'."
    }
    Write-Host "Desktop shortcut: $($shortcut[0].FullName)"

    $installRoot = Split-Path -Parent $app.FullName
    $uninstaller = Resolve-Uninstaller $entries $installRoot
    if (-not $uninstaller) {
        throw 'NSIS installation succeeded but no uninstaller could be resolved.'
    }
    $uninstallArgs = @()
    if (-not [string]::IsNullOrWhiteSpace($uninstaller.Args)) {
        $uninstallArgs += $uninstaller.Args
    }
    if (($uninstallArgs -join ' ') -notmatch '(?i)(^|\s)/S($|\s)') {
        $uninstallArgs += '/S'
    }
    $uninstall = Start-Process -FilePath $uninstaller.Exe -ArgumentList $uninstallArgs -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) {
        throw "NSIS silent uninstall failed with exit code $($uninstall.ExitCode)."
    }
    for ($attempt = 0; $attempt -lt 20 -and (Test-Path -LiteralPath $app.FullName); $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path -LiteralPath $app.FullName) {
        throw "NSIS silent uninstall completed but the application executable still exists: $($app.FullName)"
    }
    Write-Host 'NSIS install, desktop shortcut, and uninstall lifecycle: PASS'
}
else {
    $stream = [System.IO.File]::OpenRead($installer.FullName)
    try {
        $signatureBytes = New-Object byte[] 8
        [void]$stream.Read($signatureBytes, 0, 8)
    }
    finally {
        $stream.Dispose()
    }
    $oleSignature = [byte[]](0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1)
    if (($signatureBytes -join ',') -ne ($oleSignature -join ',')) {
        throw 'MSI installer does not have a valid Windows Installer compound-file header.'
    }

    $adminRoot = Join-Path $env:RUNNER_TEMP 'dhad-msi-admin-image'
    $msiLog = Join-Path $env:RUNNER_TEMP 'dhad-msi-admin.log'
    Remove-Item -LiteralPath $adminRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $msiLog -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $adminRoot | Out-Null
    $arguments = @('/a', $installer.FullName, '/qn', "TARGETDIR=$adminRoot", '/l*v', $msiLog)
    $process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        if (Test-Path -LiteralPath $msiLog) { Get-Content -LiteralPath $msiLog -Tail 200 | Write-Host }
        throw "MSI administrative extraction failed with exit code $($process.ExitCode)."
    }
    $app = Get-ChildItem -Path $adminRoot -Filter $expectedExe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $app) {
        throw "MSI database opened successfully but the administrative image contains no $expectedExe."
    }
    if ($app.Length -lt 1MB) {
        throw "MSI administrative image contains an unexpectedly small application executable: $($app.FullName)"
    }
    Test-PeHeader $app.FullName 'MSI application payload'
    Remove-Item -LiteralPath $adminRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'MSI administrative extraction and payload validation: PASS'
}

$signature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
Write-Host "Authenticode status: $($signature.Status)"
if ($env:DHAD_REQUIRE_WINDOWS_SIGNED -eq '1' -and $signature.Status -ne 'Valid') {
    throw "A valid Authenticode signature is required, got $($signature.Status)."
}
Write-Host "Windows $bundle installer verification: PASS"
