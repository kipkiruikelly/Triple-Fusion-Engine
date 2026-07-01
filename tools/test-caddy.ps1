# test-caddy.ps1
# One-shot elevated smoke test: imports Caddy's already-generated internal
# CA into the Windows trust store directly (more reliable in a headless/
# RunAs context than relying on Caddy's own runtime auto-install, which can
# stall waiting on a UI prompt that never appears), then runs Caddy briefly
# to confirm the reverse proxy + HTTPS + redirect all work.

Start-Transcript -Path (Join-Path $PSScriptRoot "test-caddy.log") -Force
$ErrorActionPreference = "Continue"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Output "SCRIPT ERROR: must run as Administrator"
    Stop-Transcript
    exit 1
}

$ProjectDir = Split-Path -Parent $PSScriptRoot
$CaddyDir   = Join-Path $ProjectDir "caddy"
$RootCrt    = Join-Path $CaddyDir "data\caddy\pki\authorities\local\root.crt"
$env:XDG_DATA_HOME = Join-Path $CaddyDir "data"

if (Test-Path $RootCrt) {
    Write-Output "--- importing Caddy internal root CA into LocalMachine\Root ---"
    Import-Certificate -FilePath $RootCrt -CertStoreLocation "Cert:\LocalMachine\Root"
} else {
    Write-Output "root.crt not found at $RootCrt - was CA ever generated?"
}

Write-Output "--- confirm CA present in store ---"
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*Caddy*" } | Select-Object Subject, Thumbprint, NotAfter

$proc = Start-Process -FilePath (Join-Path $PSScriptRoot "caddy.exe") `
    -ArgumentList "run","--config","Caddyfile","--adapter","caddyfile" `
    -WorkingDirectory $CaddyDir `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $CaddyDir "test-run.out.log") `
    -RedirectStandardError (Join-Path $CaddyDir "test-run.err.log")

Start-Sleep -Seconds 6

Write-Output "--- listening sockets for this process ---"
Get-NetTCPConnection -OwningProcess $proc.Id -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, State
Write-Output "--- all listeners on 443/80 ---"
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 443 -or $_.LocalPort -eq 80 } | Select-Object LocalAddress, LocalPort, OwningProcess
Write-Output "--- Test-NetConnection to 443 ---"
$tnc = Test-NetConnection -ComputerName localhost -Port 443 -WarningAction SilentlyContinue
Write-Output "TcpTestSucceeded: $($tnc.TcpTestSucceeded)"

Write-Output "--- curl version / TLS backend ---"
& curl.exe --version

Write-Output "--- HTTPS test verbose ---"
& curl.exe -v https://localhost/health 2>&1

Write-Output "--- HTTPS test (trusted, no -k) ---"
& curl.exe -s -o NUL -w "HTTP %{http_code}`n" https://localhost/health
& curl.exe -s https://localhost/health
Write-Output ""

Write-Output "--- HTTP redirect test ---"
& curl.exe -s -o NUL -w "HTTP redirect status: %{http_code} -> %{redirect_url}`n" http://localhost/health

Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Write-Output "--- caddy stderr tail ---"
Get-Content (Join-Path $CaddyDir "test-run.err.log") -Tail 15 -ErrorAction SilentlyContinue

Stop-Transcript
