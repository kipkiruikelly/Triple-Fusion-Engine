# add-tailscale-firewall.ps1
# Adds a firewall rule for caddy.exe scoped precisely to the Tailscale
# interface (not to a Public/Private profile category, which Windows could
# reassign later).

Start-Transcript -Path (Join-Path $PSScriptRoot "add-tailscale-firewall.log") -Force
$ErrorActionPreference = "Continue"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Output "SCRIPT ERROR: must run as Administrator"
    Stop-Transcript
    exit 1
}

$CaddyExe = Join-Path $PSScriptRoot "caddy.exe"

Remove-NetFirewallRule -DisplayName "Caddy Reverse Proxy (Tailscale)" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Caddy Reverse Proxy (Tailscale)" `
    -Direction Inbound -Action Allow -Program $CaddyExe `
    -Protocol TCP -LocalPort 443,80 -InterfaceAlias "Tailscale" | Out-Null

Write-Output "--- rule created ---"
Get-NetFirewallRule -DisplayName "Caddy Reverse Proxy (Tailscale)" | Select-Object DisplayName, Direction, Action, Enabled

Stop-Transcript
