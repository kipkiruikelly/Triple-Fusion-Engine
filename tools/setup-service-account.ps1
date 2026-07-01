# setup-service-account.ps1
# Creates a dedicated, restricted local account for the StockMarketPredictor
# service, grants it only the rights/paths it needs, and reconfigures the
# existing NSSM service to run as this account instead of LocalSystem.

Start-Transcript -Path (Join-Path $PSScriptRoot "setup-service-account.log") -Force
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
$ServiceName = "StockMarketPredictor"
$AccountName = "svc-stockpredictor"
$PwFile      = "C:\ServiceCreds\svc-stockpredictor_password.txt"

# LSA rights helper (LsaAddAccountRights via P/Invoke - no ntrights.exe on modern Windows)
$lsaSrc = @'
using System;
using System.Runtime.InteropServices;
public class LsaRights {
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

function Grant-LsaRight {
    param([string]$AccountName, [string]$Right)
    $sid = (New-Object System.Security.Principal.NTAccount($AccountName)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    [LsaRights]::GrantRight($sid, $Right)
    Write-Output "Granted $Right to $AccountName ($sid)"
}

# 1. Create the account (or reuse if it already exists from a prior run)
$existingUser = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue
if (-not $existingUser) {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $rawPw = ([Convert]::ToBase64String($bytes)) + "aA1!"
    $securePw = ConvertTo-SecureString $rawPw -AsPlainText -Force

    New-LocalUser -Name $AccountName -Password $securePw -FullName "StockMarketPredictor Service Account" -Description "Restricted svc account, no interactive/RDP logon" -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires | Out-Null

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
Grant-LsaRight -AccountName $AccountName -Right "SeServiceLogonRight"
Grant-LsaRight -AccountName $AccountName -Right "SeDenyInteractiveLogonRight"
Grant-LsaRight -AccountName $AccountName -Right "SeDenyRemoteInteractiveLogonRight"

# 4. NTFS permissions: read+execute on the whole project, read+write only on instance/ and logs/
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "instance") | Out-Null

icacls $ProjectDir /grant "${AccountName}:(OI)(CI)(RX)" /T | Out-Null
icacls (Join-Path $ProjectDir "instance") /grant "${AccountName}:(OI)(CI)(M)" /T | Out-Null
icacls (Join-Path $ProjectDir "logs") /grant "${AccountName}:(OI)(CI)(M)" /T | Out-Null
Write-Output "NTFS ACLs applied: RX on project root, Modify on instance/ and logs/."

# 5. Reconfigure the NSSM service to log on as this account
& $Nssm stop $ServiceName 2>&1
& $Nssm set $ServiceName ObjectName ".\$AccountName" $rawPw 2>&1
& $Nssm start $ServiceName 2>&1

Start-Sleep -Seconds 3
& $Nssm status $ServiceName 2>&1

Stop-Transcript
