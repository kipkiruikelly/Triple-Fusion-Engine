# setup-caddy-service.ps1
# Creates a dedicated, restricted local account for Caddy, grants it only
# the paths it needs, registers Caddy as its own NSSM service running as
# that account, and opens a Private-profile-only firewall rule scoped to
# caddy.exe specifically (not a blanket port rule).

Start-Transcript -Path (Join-Path $PSScriptRoot "setup-caddy-service.log") -Force
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

$ProjectDir  = Split-Path -Parent $PSScriptRoot
$Nssm        = Join-Path $PSScriptRoot "nssm.exe"
$CaddyExe    = Join-Path $PSScriptRoot "caddy.exe"
$CaddyDir    = Join-Path $ProjectDir "caddy"
$ServiceName = "CaddyReverseProxy"
$AccountName = "svc-caddy"
$PwFile      = "C:\ServiceCreds\svc-caddy_password.txt"

$lsaSrc = @'
using System;
using System.Runtime.InteropServices;
public class LsaRights2 {
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_UNICODE_STRING { public ushort Length; public ushort MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_OBJECT_ATTRIBUTES { public int Length; public IntPtr RootDirectory; public IntPtr ObjectName; public int Attributes; public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService; }
    [DllImport("advapi32.dll", SetLastError = true, PreserveSig = true)]
    static extern uint LsaOpenPolicy(ref LSA_UNICODE_STRING SystemName, ref LSA_OBJECT_ATTRIBUTES ObjectAttributes, int DesiredAccess, out IntPtr PolicyHandle);
    [DllImport("advapi32.dll", SetLastError = true, PreserveSig = true)]
    static extern uint LsaAddAccountRights(IntPtr PolicyHandle, byte[] AccountSid, LSA_UNICODE_STRING[] UserRights, int CountOfRights);
    [DllImport("advapi32.dll")]
    static extern int LsaClose(IntPtr ObjectHandle);
    [DllImport("advapi32.dll")]
    static extern bool ConvertStringSidToSid(string StringSid, out IntPtr Sid);
    [DllImport("advapi32.dll")]
    static extern int GetLengthSid(IntPtr pSid);

    static LSA_UNICODE_STRING ToLsaString(string s) {
        var r = new LSA_UNICODE_STRING();
        r.Buffer = Marshal.StringToHGlobalUni(s);
        r.Length = (ushort)(s.Length * 2);
        r.MaximumLength = (ushort)((s.Length + 1) * 2);
        return r;
    }

    public static void GrantRight(string sid, string right) {
        IntPtr sidPtr;
        if (!ConvertStringSidToSid(sid, out sidPtr)) throw new Exception("Bad SID: " + sid);
        byte[] sidBytes = new byte[GetLengthSid(sidPtr)];
        Marshal.Copy(sidPtr, sidBytes, 0, sidBytes.Length);

        LSA_UNICODE_STRING system = new LSA_UNICODE_STRING();
        LSA_OBJECT_ATTRIBUTES oa = new LSA_OBJECT_ATTRIBUTES();
        IntPtr policyHandle;
        uint status = LsaOpenPolicy(ref system, ref oa, 0x0810, out policyHandle);
        if (status != 0) throw new Exception("LsaOpenPolicy failed: " + status);

        var rights = new LSA_UNICODE_STRING[] { ToLsaString(right) };
        status = LsaAddAccountRights(policyHandle, sidBytes, rights, 1);
        LsaClose(policyHandle);
        if (status != 0) throw new Exception("LsaAddAccountRights failed for " + right + ": " + status);
    }
}
'@
Add-Type -TypeDefinition $lsaSrc -ErrorAction Stop

function Grant-LsaRight2 {
    param([string]$AccountName, [string]$Right)
    $sid = (New-Object System.Security.Principal.NTAccount($AccountName)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    [LsaRights2]::GrantRight($sid, $Right)
    Write-Output "Granted $Right to $AccountName ($sid)"
}

# 1. Create the account (or reuse if it already exists from a prior run)
$existingUser = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue
if (-not $existingUser) {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $rawPw = ([Convert]::ToBase64String($bytes)) + "aA1!"
    $securePw = ConvertTo-SecureString $rawPw -AsPlainText -Force

    New-LocalUser -Name $AccountName -Password $securePw -FullName "Caddy Reverse Proxy Service Account" -Description "Restricted svc account, no interactive/RDP logon" -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires | Out-Null

    New-Item -ItemType Directory -Force -Path (Split-Path $PwFile) | Out-Null
    Set-Content -Path $PwFile -Value $rawPw -NoNewline
    icacls $PwFile /inheritance:r /grant:r "*S-1-5-32-544:(R)" "SYSTEM:(R)" | Out-Null
    Write-Output "Created local account '$AccountName'."
} else {
    Write-Output "Account '$AccountName' already exists - reusing it."
    if (-not (Test-Path $PwFile)) {
        throw "Account exists but password recovery file is missing at $PwFile - cannot reconfigure NSSM without it. Aborting."
    }
}
$rawPw = Get-Content -Path $PwFile -Raw

# 2. Confirm it is NOT in any elevated/interactive-logon group
foreach ($grp in @("Administrators", "Remote Desktop Users", "Users")) {
    try {
        if (Get-LocalGroupMember -Group $grp -Member $AccountName -ErrorAction SilentlyContinue) {
            Remove-LocalGroupMember -Group $grp -Member $AccountName
            Write-Output "Removed $AccountName from group '$grp'."
        }
    } catch {
        # group lookup/removal failures for a group the account was never in are expected; ignore
    }
}

# 3. Grant SeServiceLogonRight; explicitly deny interactive/RDP logon (defense-in-depth)
Grant-LsaRight2 -AccountName $AccountName -Right "SeServiceLogonRight"
Grant-LsaRight2 -AccountName $AccountName -Right "SeDenyInteractiveLogonRight"
Grant-LsaRight2 -AccountName $AccountName -Right "SeDenyRemoteInteractiveLogonRight"

# 4. NTFS permissions: read+execute on caddy.exe and the caddy/ config tree,
#    read+write only on caddy/data (cert storage) and caddy/logs (access logs)
New-Item -ItemType Directory -Force -Path (Join-Path $CaddyDir "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $CaddyDir "data") | Out-Null

icacls $Nssm /grant "${AccountName}:(RX)" | Out-Null
icacls $CaddyExe /grant "${AccountName}:(RX)" | Out-Null
icacls $CaddyDir /grant "${AccountName}:(OI)(CI)(RX)" /T | Out-Null
icacls (Join-Path $CaddyDir "data") /grant "${AccountName}:(OI)(CI)(M)" /T | Out-Null
icacls (Join-Path $CaddyDir "logs") /grant "${AccountName}:(OI)(CI)(M)" /T | Out-Null
Write-Output "NTFS ACLs applied: RX on nssm.exe, caddy.exe and caddy/ tree, Modify on caddy/data and caddy/logs."

# 5. Register/reconfigure the NSSM service to run as this account
# nssm writes routine/expected messages (e.g. "service has not been
# started") to stderr; under $ErrorActionPreference=Stop, PowerShell 5.1
# treats those as terminating errors regardless of 2>&1 redirection. Drop
# to Continue for the nssm calls; we verify actual state via Get-Service /
# nssm status explicitly afterward instead of relying on exceptions here.
$ErrorActionPreference = "Continue"

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    & $Nssm stop $ServiceName 2>&1
    & $Nssm remove $ServiceName confirm 2>&1
}

& $Nssm install $ServiceName $CaddyExe "run --config Caddyfile --adapter caddyfile" 2>&1
& $Nssm set $ServiceName AppDirectory $CaddyDir 2>&1
& $Nssm set $ServiceName DisplayName "Caddy Reverse Proxy (StockMarketPredictor)" 2>&1
& $Nssm set $ServiceName Description "Local HTTPS reverse proxy in front of the StockMarketPredictor waitress service" 2>&1
& $Nssm set $ServiceName Start SERVICE_AUTO_START 2>&1
& $Nssm set $ServiceName AppEnvironmentExtra "XDG_DATA_HOME=$(Join-Path $CaddyDir 'data')" 2>&1
& $Nssm set $ServiceName AppStdout (Join-Path $CaddyDir "logs\service.out.log") 2>&1
& $Nssm set $ServiceName AppStderr (Join-Path $CaddyDir "logs\service.err.log") 2>&1
& $Nssm set $ServiceName AppRotateFiles 1 2>&1
& $Nssm set $ServiceName AppRotateOnline 1 2>&1
& $Nssm set $ServiceName AppRotateBytes 10485760 2>&1
& $Nssm set $ServiceName AppExit Default Restart 2>&1
& $Nssm set $ServiceName AppRestartDelay 5000 2>&1
& $Nssm set $ServiceName ObjectName ".\$AccountName" $rawPw 2>&1

# 6. Firewall: inbound rule scoped to Private profile only, restricted to caddy.exe
Remove-NetFirewallRule -DisplayName "Caddy Reverse Proxy (StockMarketPredictor)" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Caddy Reverse Proxy (StockMarketPredictor)" `
    -Direction Inbound -Action Allow -Program $CaddyExe `
    -Protocol TCP -LocalPort 443,80 -Profile Private | Out-Null
Write-Output "Firewall rule added: TCP 443,80 for caddy.exe, Private profile only."

& $Nssm start $ServiceName 2>&1
Start-Sleep -Seconds 3
& $Nssm status $ServiceName 2>&1

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Output "RESULT: $ServiceName is Running"
} else {
    Write-Output "RESULT: $ServiceName is NOT running (status: $($svc.Status))"
}

Stop-Transcript
