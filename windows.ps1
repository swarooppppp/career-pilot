param(
    [Parameter(Position=0)]
    [ValidateSet('setup','check','start','stop','status','install','uninstall','update','logs','restore','backup')]
    [string]$Action = 'status',
    [Parameter(Position=1)][string]$Archive,
    [switch]$Replace
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE). See the message above." }
}
if ($Action -eq 'setup') {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.12 from python.org with the Python launcher, then reopen PowerShell.' }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows and reopen PowerShell.' }
    if (-not (Test-Path -LiteralPath $Python)) { Invoke-Checked 'py' @('-3.12','-m','venv','.venv') }
    Invoke-Checked $Python @('-c','import sys; assert sys.version_info[:2] == (3,12), "Use a Python 3.12 virtual environment"')
    Invoke-Checked $Python @('-m','pip','install','--upgrade','pip')
    Invoke-Checked $Python @('-m','pip','install','-r','requirements.txt','-c','constraints.txt')
    Invoke-Checked $Python @('-m','playwright','install','chromium')
    Invoke-Checked $Python @('automation/windows_check.py','--skip-config')
    Write-Host 'Setup complete. Copy .env privately, restore the migration archive, then run check and start.'
    exit 0
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run the setup command first.' }
if ($Action -eq 'check') {
    Invoke-Checked $Python @('automation/windows_check.py')
} elseif ($Action -in @('backup','restore')) {
    if (-not $Archive) { throw 'Supply an archive path as the second argument.' }
    $Arguments = @('automation/migrate_local.py',$Action,$Archive)
    if ($Replace) { $Arguments += '--replace' }
    Invoke-Checked $Python $Arguments
} else {
    if ($Action -in @('start','install')) { Invoke-Checked $Python @('automation/windows_check.py') }
    Invoke-Checked $Python @('automation/windows_service.py',$Action)
}
