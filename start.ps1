# ============================================================
#  Triple Fusion Engine — Autostart Script
#  Frontend  → http://localhost:5000   (Vite dev server)
#  Backend   → http://localhost:8001   (Django DRF)
#  Public    → auto-detected from ngrok API
# ============================================================

$projectRoot = $PSScriptRoot
$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$manageFile  = Join-Path $projectRoot "django_backend\manage.py"
$frontendDir = Join-Path $projectRoot "frontend"
$ngrokConfig = Join-Path $projectRoot "ngrok.yml"

function Write-Header {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "   Triple Fusion Engine" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

Write-Header

# ----- 1. Validate prerequisites -----
if (-Not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Python venv not found. Run: python -m venv .venv" -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}
try { npm --version | Out-Null } catch {
    Write-Host "[ERROR] Node/npm not found. Install Node.js 18+." -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}
$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
if (-Not $ngrokCmd) {
    Write-Host "[WARN] ngrok not found — public URL will not be available." -ForegroundColor DarkYellow
    $skipNgrok = $true
} else {
    $skipNgrok = $false
}

# ----- 2. Free ports 5000 and 8001 -----
Write-Host ""
Write-Host "[*] Freeing ports 5000 and 8001..." -ForegroundColor DarkGray
@(5000, 8001, 4040) | ForEach-Object {
    $pid_ = (Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
    if ($pid_) {
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
        Write-Host "    Killed PID $pid_ on port $_" -ForegroundColor DarkGray
    }
}
Start-Sleep -Seconds 1

# ----- 3. Start Django backend on 8001 -----
Write-Host ""
Write-Host "[1/3] Starting Django backend → http://localhost:8001" -ForegroundColor Yellow
$django = Start-Process -FilePath $venvPython `
    -ArgumentList "`"$manageFile`" runserver 0.0.0.0:8001" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Minimized `
    -PassThru
Write-Host "      PID: $($django.Id)" -ForegroundColor DarkGray
Start-Sleep -Seconds 3

# ----- 4. Start Vite frontend on 5000 -----
Write-Host "[2/3] Starting Vite dev server → http://localhost:5000" -ForegroundColor Green
$vite = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run dev" `
    -WorkingDirectory $frontendDir `
    -WindowStyle Minimized `
    -PassThru
Write-Host "      PID: $($vite.Id)" -ForegroundColor DarkGray
Start-Sleep -Seconds 3

# ----- 5. Start ngrok tunnels -----
if (-Not $skipNgrok) {
    Write-Host "[3/3] Starting ngrok tunnels..." -ForegroundColor Magenta
    $ngrok = Start-Process -FilePath "ngrok" `
        -ArgumentList "start --all --config `"$ngrokConfig`"" `
        -WorkingDirectory $projectRoot `
        -WindowStyle Minimized `
        -PassThru
    Write-Host "      PID: $($ngrok.Id)" -ForegroundColor DarkGray

    # Poll ngrok local API to get the public URLs
    Write-Host ""
    Write-Host "  Waiting for ngrok tunnels to open..." -ForegroundColor DarkGray
    $frontendUrl = $null
    $backendUrl  = $null
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        try {
            $tunnelData = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -ErrorAction Stop
            foreach ($t in $tunnelData.tunnels) {
                if ($t.config.addr -match "5000") { $frontendUrl = $t.public_url }
                if ($t.config.addr -match "8001") { $backendUrl  = $t.public_url }
            }
            if ($frontendUrl -and $backendUrl) { break }
        } catch { }
    }
}

# ----- 6. Print summary -----
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ALL SERVICES RUNNING" -ForegroundColor White
Write-Host ""
Write-Host "  LOCAL  (same machine)" -ForegroundColor DarkGray
Write-Host "    Frontend : http://localhost:5000" -ForegroundColor Green
Write-Host "    Backend  : http://localhost:8001" -ForegroundColor Yellow
Write-Host ""
if (-Not $skipNgrok) {
    Write-Host "  PUBLIC (share with anyone, anywhere)" -ForegroundColor DarkGray
    if ($frontendUrl) {
        Write-Host "    App URL  : $frontendUrl" -ForegroundColor Cyan
    } else {
        Write-Host "    App URL  : Check http://127.0.0.1:4040 (ngrok dashboard)" -ForegroundColor DarkYellow
    }
    if ($backendUrl) {
        Write-Host "    API URL  : $backendUrl/api/" -ForegroundColor Cyan
    }
    Write-Host ""
    Write-Host "  NGROK DASHBOARD (inspect requests)" -ForegroundColor DarkGray
    Write-Host "    http://127.0.0.1:4040" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  PIDs: Django=$($django.Id)  Vite=$($vite.Id)" $(if(-Not $skipNgrok){"  ngrok=$($ngrok.Id)"}) -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ----- 7. Open browser -----
Start-Sleep -Seconds 1
if ($frontendUrl) {
    Write-Host "[*] Opening public URL in browser: $frontendUrl" -ForegroundColor Cyan
    Start-Process $frontendUrl
} else {
    Write-Host "[*] Opening local URL in browser: http://localhost:5000" -ForegroundColor Green
    Start-Process "http://localhost:5000"
}

# ----- 8. Wait / clean shutdown -----
Write-Host ""
Write-Host "Press Ctrl+C or close this window to stop all services." -ForegroundColor DarkGray
Write-Host ""

try {
    $ids = @($django.Id, $vite.Id)
    if (-Not $skipNgrok) { $ids += $ngrok.Id }
    Wait-Process -Id $ids -ErrorAction SilentlyContinue
} finally {
    Write-Host ""
    Write-Host "[*] Shutting down all services..." -ForegroundColor Red
    Stop-Process -Id $django.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $vite.Id  -Force -ErrorAction SilentlyContinue
    if (-Not $skipNgrok -and $ngrok) {
        Stop-Process -Id $ngrok.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "    All stopped. Goodbye!" -ForegroundColor DarkGray
}
