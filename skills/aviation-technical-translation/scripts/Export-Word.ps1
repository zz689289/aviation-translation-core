#requires -Version 5.1
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$InputPath,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [ValidateSet('UpdateSave','ReadOnly')][string]$Mode='UpdateSave',
 [ValidateRange(15,600)][int]$WordTimeoutSeconds=90,
 [ValidateRange(1,3600)][int]$QueueTimeoutSeconds=600,
 [string[]]$ExpectedText=@(),
 [string]$RuntimeDirectory,
 [switch]$CheckRuntimeOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(-not $RuntimeDirectory) {
 $RuntimeDirectory=Join-Path $PSScriptRoot 'word_export\v2.0.0\runtime'
 if(-not (Test-Path -LiteralPath (Join-Path $RuntimeDirectory 'Export-Word.ps1') -PathType Leaf)) {
  $RuntimeDirectory=Join-Path $env:USERPROFILE '.codex\skills\aviation-technical-translation\scripts\word_export\v2.0.0\runtime'
 }
}
$pins=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'word_runtime.sha256.json') -Raw | ConvertFrom-Json
foreach($entry in $pins.PSObject.Properties) {
 $file=Join-Path $RuntimeDirectory $entry.Name
 if(-not (Test-Path -LiteralPath $file -PathType Leaf)) {throw 'VERIFIED_WORD_RUNTIME_MISSING'}
 if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {throw 'WORD_RUNTIME_HASH_MISMATCH'}
}
if($CheckRuntimeOnly) {Write-Output '{"Status":"PASS","WordStarted":false}';return}
# The approved runtime keeps its exact identity, process-ownership and permission
# boundaries. This bridge neither changes its code nor installs configuration.
& (Join-Path $RuntimeDirectory 'Export-Word.ps1') -InputPath $InputPath -OutputDirectory $OutputDirectory -Mode $Mode -WordTimeoutSeconds $WordTimeoutSeconds -QueueTimeoutSeconds $QueueTimeoutSeconds -ExpectedText $ExpectedText
exit $LASTEXITCODE
