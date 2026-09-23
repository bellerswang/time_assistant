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

echo [SUCCESS] HTTP Static Server configured.
echo.
echo ===================================================
echo   Access Links:
echo ===================================================
echo   1. PC Computer Local Access:
echo      http://localhost:%FRONTEND_PORT%/
echo.
echo   Local access only. Mobile recording requires an HTTPS deployment.
echo.
echo   For phone access, use the HTTPS Cloud Run site after setup.
echo ===================================================
echo.

:: Automatically open browser on PC
echo [INFO] Opening default browser...
start "" http://localhost:%FRONTEND_PORT%/

echo [INFO] Starting Python HTTP static server on port %FRONTEND_PORT% (Press Ctrl+C to stop)...
echo [INFO] Logs will also be written to %FRONTEND_LOG_FILE%
echo.
python serve_frontend.py --bind 127.0.0.1 --port %FRONTEND_PORT% 1>"%FRONTEND_LOG_FILE%" 2>&1

pause
