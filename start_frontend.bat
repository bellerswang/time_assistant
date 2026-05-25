@echo off
title Loomi Frontend Launcher
echo ===================================================
echo   Loomi Smart Time Assistant - Frontend Server
echo ===================================================
echo.

cd /d "%~dp0"

:: Use virtual environment Python to get the active LAN IP address
set LAN_IP=127.0.0.1
if exist "venv\Scripts\python.exe" (
    for /f "delims=" %%a in ('venv\Scripts\python.exe backend\get_ip.py') do (
        set LAN_IP=%%a
    )
)

echo [SUCCESS] HTTP Static Server configured.
echo.
echo ===================================================
echo   Access Links:
echo ===================================================
echo   1. PC Computer Local Access:
echo      http://localhost:8000/
echo.
echo   2. iPhone Mobile Access (Must be on the SAME WiFi):
echo      http://%LAN_IP%:8000/
echo.
echo   * iOS PWA Installation:
echo     Open the iPhone access link in Safari, tap the
echo     "Share" icon at the bottom, and select
echo     "Add to Home Screen" to install it.
echo ===================================================
echo.

:: Automatically open browser on PC
echo [INFO] Opening default browser...
start http://localhost:8000/

echo [INFO] Starting Python HTTP static server on port 8000 (Press Ctrl+C to stop)...
echo.
python -m http.server 8000

pause
