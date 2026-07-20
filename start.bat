@echo off
title Triple Fusion Engine - Dev Launcher
echo.
echo  Starting Triple Fusion Engine...
echo  Frontend : http://localhost:5000
echo  Backend  : http://localhost:8001
echo.

:: Run the PowerShell launcher (bypass execution policy for this session only)
powershell.exe -ExecutionPolicy Bypass -File "%~dp0start.ps1"

pause
