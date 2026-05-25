@echo off
title Loomi Frontend Launcher
setlocal enabledelayedexpansion
echo ===================================================
echo   Loomi Smart Time Assistant - Frontend Server
echo ===================================================
echo.

cd /d "%~dp0"
set "FRONTEND_PORT=8000"
set "FRONTEND_LOG_DIR=%~dp0backend\logs"
set "FRONTEND_LOG_FILE=%FRONTEND_LOG_DIR%\frontend_%FRONTEND_PORT%.log"

if not exist "%FRONTEND_LOG_DIR%" mkdir "%FRONTEND_LOG_DIR%"

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
echo      http://localhost:%FRONTEND_PORT%/
echo.
echo   2. iPhone Mobile Access (Must be on the SAME WiFi):
echo      http://%LAN_IP%:%FRONTEND_PORT%/
echo.
echo   * iOS PWA Installation:
echo     Open the iPhone access link in Safari, tap the
echo     "Share" icon at the bottom, and select
echo     "Add to Home Screen" to install it.
echo ===================================================
echo.

:: Automatically open browser on PC
echo [INFO] Opening default browser...
start "" http://localhost:%FRONTEND_PORT%/

echo [INFO] Starting Python HTTP static server on port %FRONTEND_PORT% (Press Ctrl+C to stop)...
echo [INFO] Logs will also be written to %FRONTEND_LOG_FILE%
echo.
python -m http.server %FRONTEND_PORT% 1>"%FRONTEND_LOG_FILE%" 2>&1

pause
