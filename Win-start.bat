@echo off
title Triple Fusion Engine
echo.
echo  ============================================================
echo   Triple Fusion Engine - Dev Launcher
echo   Frontend  : http://localhost:5000
echo   Backend   : http://localhost:8001
echo  ============================================================
echo.

echo [1/4] Stopping any existing processes on ports 5000, 8001...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000') do taskkill /f /pid %%a 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001') do taskkill /f /pid %%a 2>nul
timeout /t 1 /nobreak >nul

echo [2/4] Verifying database migrations...
call .venv\Scripts\python.exe django_backend\manage.py migrate --run-syncdb 2>nul

echo [3/4] Starting Django API backend on http://localhost:8001...
start "Django Backend :8001" /min .venv\Scripts\python.exe django_backend\manage.py runserver 0.0.0.0:8001

timeout /t 2 /nobreak >nul

echo [4/4] Starting React Vite frontend on http://localhost:5000...
cd frontend
npm run dev
