# Windows PowerShell 5.1. Configuration belongs to the Word export operator.
function Read-WordExportConfiguration {
    $file = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'AviationTranslation\word-export.json'
    if (-not [IO.File]::Exists($file)) { throw 'WORD_EXPORT_ENROLLMENT_REQUIRED' }
    $cfg = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $sid = New-Object System.Security.Principal.SecurityIdentifier([string]$cfg.UserSid)
    if ($sid.Value -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
        throw 'WORD_EXPORT_OPERATOR_MISMATCH'
    }
    $python = [string]$cfg.Python
    if ($python -notmatch '^[A-Za-z]:[\\/]' -or [IO.Path]::GetExtension($python) -ine '.exe' -or -not [IO.File]::Exists($python)) {
        throw 'CONFIGURED_PYTHON_EXECUTABLE_MISSING'
    }
    return [pscustomobject]@{ UserSid = $sid.Value; Python = [IO.Path]::GetFullPath($python) }
}
