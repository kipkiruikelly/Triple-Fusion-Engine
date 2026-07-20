# ============================================================
#  Triple Fusion Engine - Autostart Script
#  Frontend  → http://localhost:5000   (Vite dev server)
#  Backend   → http://localhost:8001   (Django DRF)
# ============================================================

$projectRoot = $PSScriptRoot
$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$venvPip     = Join-Path $projectRoot ".venv\Scripts\pip.exe"
$manageFile  = Join-Path $projectRoot "django_backend\manage.py"
$frontendDir = Join-Path $projectRoot "frontend"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Triple Fusion Engine — Dev Autostart" -ForegroundColor Cyan
Write-Host "   Frontend  → http://localhost:5000" -ForegroundColor Green
Write-Host "   Backend   → http://localhost:8001" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ----- 1. Check .venv exists -----
if (-Not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Python venv not found at $venvPython" -ForegroundColor Red
    Write-Host "        Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ----- 2. Check Node / npm -----
try { npm --version | Out-Null }
catch {
    Write-Host "[ERROR] Node/npm not found. Please install Node.js 18+." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ----- 3. Kill anything already on ports 5000 or 8001 -----
Write-Host "[*] Freeing ports 5000 and 8001 if occupied..." -ForegroundColor DarkGray
@(5000, 8001) | ForEach-Object {
    $pid_ = (Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue).OwningProcess
    if ($pid_) {
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
        Write-Host "    Killed PID $pid_ on port $_" -ForegroundColor DarkGray
    }
}
Start-Sleep -Seconds 1

# ----- 4. Start Django backend on port 8001 -----
Write-Host "[1/2] Starting Django backend on port 8001..." -ForegroundColor Yellow
$django = Start-Process -FilePath $venvPython `
    -ArgumentList "$manageFile runserver 0.0.0.0:8001" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Normal `
    -PassThru

Write-Host "      Django PID: $($django.Id)" -ForegroundColor DarkGray
Start-Sleep -Seconds 3

# ----- 5. Start Vite frontend on port 5000 -----
Write-Host "[2/2] Starting Vite dev server on port 5000..." -ForegroundColor Green
$vite = Start-Process -FilePath "npm" `
    -ArgumentList "run dev" `
    -WorkingDirectory $frontendDir `
    -WindowStyle Normal `
    -PassThru

Write-Host "      Vite PID: $($vite.Id)" -ForegroundColor DarkGray
Start-Sleep -Seconds 2

# ----- 6. Open browser -----
Write-Host ""
Write-Host "[*] Opening http://localhost:5000 in your browser..." -ForegroundColor Cyan
Start-Sleep -Seconds 2
Start-Process "http://localhost:5000"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Both servers are running. Close this window to STOP both." -ForegroundColor White
Write-Host "  Django PID : $($django.Id)" -ForegroundColor Yellow
Write-Host "  Vite   PID : $($vite.Id)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ----- 7. Wait — stop both processes when user presses Ctrl+C or closes -----
try {
    Write-Host "Press Ctrl+C to stop both servers..." -ForegroundColor DarkGray
    Wait-Process -Id $django.Id, $vite.Id
} finally {
    Write-Host ""
    Write-Host "[*] Shutting down servers..." -ForegroundColor Red
    Stop-Process -Id $django.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $vite.Id  -Force -ErrorAction SilentlyContinue
    Write-Host "    Done. Goodbye!" -ForegroundColor DarkGray
}
