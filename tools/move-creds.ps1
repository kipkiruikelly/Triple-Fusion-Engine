# move-creds.ps1
# One-time migration: move the two service-account password recovery files
# out of the project repo entirely into C:\ServiceCreds\, ACL-restricted to
# Administrators + SYSTEM only, no inheritance. Does not touch any running
# service - these files are only read by the setup scripts themselves.

Start-Transcript -Path (Join-Path $PSScriptRoot "move-creds.log") -Force
$ErrorActionPreference = "Stop"
trap {
    Write-Output "SCRIPT ERROR: $($_.Exception.Message)"
    Write-Output $_.ScriptStackTrace
    Stop-Transcript
    exit 1
}

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This script must be run as Administrator."
}

$ProjectDir = Split-Path -Parent $PSScriptRoot
$CredsDir   = "C:\ServiceCreds"

$OldStockPw = Join-Path $ProjectDir "instance\svc_account_password.txt"
$OldCaddyPw = Join-Path $ProjectDir "caddy\data\svc_account_password.txt"
$NewStockPw = Join-Path $CredsDir "svc-stockpredictor_password.txt"
$NewCaddyPw = Join-Path $CredsDir "svc-caddy_password.txt"

# 1. Create C:\ServiceCreds with restricted ACL (Administrators + SYSTEM only, no inheritance)
New-Item -ItemType Directory -Force -Path $CredsDir | Out-Null
icacls $CredsDir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)(F)" "SYSTEM:(OI)(CI)(F)" | Out-Null
Write-Output "Created/secured $CredsDir"

# 2. Move (not copy) both files, renaming for clarity
if (-not (Test-Path $OldStockPw)) { throw "Source file missing: $OldStockPw" }
if (-not (Test-Path $OldCaddyPw)) { throw "Source file missing: $OldCaddyPw" }

Move-Item -Path $OldStockPw -Destination $NewStockPw -Force
Move-Item -Path $OldCaddyPw -Destination $NewCaddyPw -Force
Write-Output "Moved both files into $CredsDir"

# 3. Apply the same restriction level the files had before (Administrators + SYSTEM
#    read-only, no inheritance) at the individual file level too, defense-in-depth
icacls $NewStockPw /inheritance:r /grant:r "*S-1-5-32-544:(R)" "SYSTEM:(R)" | Out-Null
icacls $NewCaddyPw /inheritance:r /grant:r "*S-1-5-32-544:(R)" "SYSTEM:(R)" | Out-Null

# 4. Confirm no leftover copies at the old paths
Write-Output "--- old path check (should both be False) ---"
Write-Output "$OldStockPw exists: $(Test-Path $OldStockPw)"
Write-Output "$OldCaddyPw exists: $(Test-Path $OldCaddyPw)"

Write-Output "--- final ACLs ---"
icacls $CredsDir
icacls $NewStockPw
icacls $NewCaddyPw

Stop-Transcript
