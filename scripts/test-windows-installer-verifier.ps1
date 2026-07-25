$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$env:DHAD_WINDOWS_VERIFIER_LIBRARY_ONLY = '1'
. (Join-Path $PSScriptRoot 'verify-windows-installer.ps1')

# The product name and version are read from the effective Tauri configuration by
# the verifier itself. Deriving the fixtures from those values instead of hard-coding
# them is what keeps a version bump from silently breaking this contract job: the
# previous fixtures pinned 1.0.18 and would have rejected every later release.
if ([string]::IsNullOrWhiteSpace($productName) -or [string]::IsNullOrWhiteSpace($productVersion)) {
    throw 'The verifier must expose the effective product name and version to its contract tests.'
}
Write-Host "Contract fixtures derived from configuration: $productName $productVersion"

if ((Get-OptionalPropertyValue ([pscustomobject]@{ Present = 'value' }) 'Present') -ne 'value') {
    throw 'Get-OptionalPropertyValue failed for an existing property.'
}
if ($null -ne (Get-OptionalPropertyValue ([pscustomobject]@{ Other = 'value' }) 'Missing')) {
    throw 'Get-OptionalPropertyValue must return null for a missing property.'
}

$missingDisplayName = [pscustomobject]@{ DisplayVersion = $productVersion }
if (Test-DhadUninstallEntry $missingDisplayName) {
    throw 'An uninstall entry with missing DisplayName must never match.'
}

$wrongName = [pscustomobject]@{ DisplayName = 'Other'; DisplayVersion = $productVersion }
if (Test-DhadUninstallEntry $wrongName) {
    throw 'An uninstall entry with a different DisplayName must never match.'
}

$matchingWithoutVersion = [pscustomobject]@{ DisplayName = $productName }
if (-not (Test-DhadUninstallEntry $matchingWithoutVersion)) {
    throw 'A matching uninstall entry without DisplayVersion should be accepted.'
}

$matching = [pscustomobject]@{ DisplayName = $productName; DisplayVersion = $productVersion }
if (-not (Test-DhadUninstallEntry $matching)) {
    throw 'A matching uninstall entry was rejected.'
}

$staleVersion = [pscustomobject]@{ DisplayName = $productName; DisplayVersion = '0.0.1' }
if (Test-DhadUninstallEntry $staleVersion) {
    throw 'An uninstall entry left behind by a different version must never match.'
}

$entryWithMissingPaths = [pscustomobject]@{ DisplayName = $productName; DisplayVersion = $productVersion }
$resolved = Resolve-Executable @($entryWithMissingPaths)
if ($null -eq $resolved -or $null -eq $resolved.Roots) {
    throw 'Resolve-Executable must tolerate missing registry path properties.'
}

Write-Host 'Windows installer verifier strict-mode contracts: PASS'
