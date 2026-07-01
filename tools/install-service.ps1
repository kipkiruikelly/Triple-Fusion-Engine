# install-service.ps1
# Installs the Stock Market Predictor app as a Windows service via nssm,
# served by waitress and bound to loopback only. Must be run elevated.

Start-Transcript -Path (Join-Path $PSScriptRoot "install-service.log") -Force
$ErrorActionPreference = "Stop"
trap {
    Write-Output "SCRIPT ERROR: $($_.Exception.Message)"
    Write-Output $_.ScriptStackTrace
    Stop-Transcript
    exit 1
}

$ProjectDir  = Split-Path -Parent $PSScriptRoot
$Nssm        = Join-Path $PSScriptRoot "nssm.exe"
$Python      = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Wsgi        = Join-Path $ProjectDir "wsgi.py"
$LogDir      = Join-Path $ProjectDir "logs"
$ServiceName = "StockMarketPredictor"
$SecretFile  = Join-Path $ProjectDir "instance\secret_key.txt"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This script must be run as Administrator."
}

# Generate the app SECRET_KEY once and persist only to a gitignored,
# admin/owner-only file — never embedded in this script or in any log.
New-Item -ItemType Directory -Force -Path (Split-Path $SecretFile) | Out-Null
if (-not (Test-Path $SecretFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    ([BitConverter]::ToString($bytes) -replace '-', '').ToLower() | Set-Content -Path $SecretFile -NoNewline
}
icacls $SecretFile /inheritance:r /grant:r "$env:USERDOMAIN\$env:USERNAME:(R)" "SYSTEM:(R)" "*S-1-5-32-544:(R)" | Out-Null
$SecretKey = Get-Content -Path $SecretFile -Raw

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Remove any pre-existing service with this name so this script is re-runnable
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    & $Nssm stop $ServiceName confirm 2>&1 | Out-Null
    & $Nssm remove $ServiceName confirm 2>&1 | Out-Null
}

& $Nssm install $ServiceName $Python $Wsgi 2>&1
& $Nssm set $ServiceName AppDirectory $ProjectDir 2>&1
& $Nssm set $ServiceName DisplayName "Stock Market Predictor" 2>&1
& $Nssm set $ServiceName Description "Local-only Flask app (BullLogic) served via waitress on 127.0.0.1, managed by nssm" 2>&1
& $Nssm set $ServiceName Start SERVICE_AUTO_START 2>&1
& $Nssm set $ServiceName AppEnvironmentExtra "SECRET_KEY=$SecretKey" "HOST=127.0.0.1" "PORT=5000" 2>&1
& $Nssm set $ServiceName AppStdout (Join-Path $LogDir "service.out.log") 2>&1
& $Nssm set $ServiceName AppStderr (Join-Path $LogDir "service.err.log") 2>&1
& $Nssm set $ServiceName AppRotateFiles 1 2>&1
& $Nssm set $ServiceName AppRotateOnline 1 2>&1
& $Nssm set $ServiceName AppRotateBytes 10485760 2>&1
& $Nssm set $ServiceName AppExit Default Restart 2>&1
& $Nssm set $ServiceName AppRestartDelay 5000 2>&1

& $Nssm start $ServiceName 2>&1

Start-Sleep -Seconds 3
& $Nssm status $ServiceName 2>&1
Stop-Transcript
