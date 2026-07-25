$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$env:DHAD_WINDOWS_VERIFIER_LIBRARY_ONLY = '1'
. (Join-Path $PSScriptRoot 'verify-windows-installer.ps1')

if ((Get-OptionalPropertyValue ([pscustomobject]@{ Present = 'value' }) 'Present') -ne 'value') {
    throw 'Get-OptionalPropertyValue failed for an existing property.'
}
if ($null -ne (Get-OptionalPropertyValue ([pscustomobject]@{ Other = 'value' }) 'Missing')) {
    throw 'Get-OptionalPropertyValue must return null for a missing property.'
}

$missingDisplayName = [pscustomobject]@{ DisplayVersion = '1.0.18' }
if (Test-DhadUninstallEntry $missingDisplayName) {
    throw 'An uninstall entry with missing DisplayName must never match.'
}

$wrongName = [pscustomobject]@{ DisplayName = 'Other'; DisplayVersion = '1.0.18' }
if (Test-DhadUninstallEntry $wrongName) {
    throw 'An uninstall entry with a different DisplayName must never match.'
}

$matchingWithoutVersion = [pscustomobject]@{ DisplayName = 'Dhad' }
if (-not (Test-DhadUninstallEntry $matchingWithoutVersion)) {
    throw 'A matching uninstall entry without DisplayVersion should be accepted.'
}

$matching = [pscustomobject]@{ DisplayName = 'Dhad'; DisplayVersion = '1.0.18' }
if (-not (Test-DhadUninstallEntry $matching)) {
    throw 'A matching uninstall entry was rejected.'
}

$entryWithMissingPaths = [pscustomobject]@{ DisplayName = 'Dhad'; DisplayVersion = '1.0.18' }
$resolved = Resolve-Executable @($entryWithMissingPaths)
if ($null -eq $resolved -or $null -eq $resolved.Roots) {
    throw 'Resolve-Executable must tolerate missing registry path properties.'
}

Write-Host 'Windows installer verifier strict-mode contracts: PASS'
