@echo off
echo Stopping any existing processes on ports 8001 and 8002...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001') do taskkill /f /pid %%a 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8002') do taskkill /f /pid %%a 2>nul

echo Verifying database migrations...
call venv\Scripts\python.exe django_backend\manage.py migrate

echo Starting Django API backend on http://localhost:8001...
start /b venv\Scripts\python.exe django_backend\manage.py runserver 0.0.0.0:8001

echo Starting React Vite frontend on http://localhost:8002...
cd frontend
npm run dev
