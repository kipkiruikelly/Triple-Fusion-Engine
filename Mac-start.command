#!/bin/bash

# Change directory to the directory where this script is located
cd "$(dirname "$0")"

# Initialize .env configuration file if missing
if [ ! -f ".env" ]; then
    echo "Initializing .env configuration file from .env.example..."
    cp .env.example .env
fi

# Kill any existing server processes on ports 8001 and 8002 to avoid conflicts
echo "Stopping any existing processes on ports 8001 and 8002..."
lsof -ti :8001 | xargs kill -9 2>/dev/null
lsof -ti :8002 | xargs kill -9 2>/dev/null

# Activate Python Virtual Environment
if [ -d "venv" ]; then
    echo "Activating Python virtual environment..."
    source venv/bin/activate
else
    echo "Warning: 'venv' directory not found. Please set up your virtual environment."
fi

# Run Django database migrations
echo "Verifying database migrations..."
./venv/bin/python django_backend/manage.py migrate

# Start Django backend in the background on port 8001
echo "Starting Django API backend on http://localhost:8001..."
./venv/bin/python django_backend/manage.py runserver 0.0.0.0:8001 &

# Start Vite React frontend on port 8002
echo "Starting React Vite frontend on http://localhost:8002..."
cd frontend
npm run dev -- --port 8002
