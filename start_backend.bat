@echo off
title Loomi Backend Launcher
setlocal enabledelayedexpansion
echo ===================================================
echo   Loomi Smart Time Assistant - Backend Launcher
echo ===================================================
echo.

cd /d "%~dp0"
set "BACKEND_PORT=11338"
set "BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%"
set "BACKEND_LOG_DIR=%~dp0backend\logs"
set "BACKEND_LOG_FILE=%BACKEND_LOG_DIR%\backend_%BACKEND_PORT%.log"

if not exist "%BACKEND_LOG_DIR%" mkdir "%BACKEND_LOG_DIR%"

echo [INFO] Project root: %cd%
echo [INFO] Backend URL: %BACKEND_URL%
echo [INFO] Log file: %BACKEND_LOG_FILE%
echo.

echo [INFO] Checking whether port %BACKEND_PORT% is already in use...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
    echo [WARN] Port %BACKEND_PORT% is already in use by PID %%p.
    echo [WARN] If this is an old backend instance, close it first or use a different port.
    echo.
    goto :skip_port_check
)
:skip_port_check

:: Check if venv exists, if not, notice user
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Virtual environment not found. Creating one...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Please check Python installation.
        pause
        exit /b 1
    )
    echo [SUCCESS] Virtual environment created successfully.
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Checking and installing dependencies...
pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [INFO] Checking optional AI configuration...
findstr /R /C:"^DEEPSEEK_API_KEY=." backend\.env >nul 2>nul
if errorlevel 1 (
    echo [WARN] DEEPSEEK_API_KEY is missing from backend\.env. Ask mode will fail until it is configured.
) else (
    echo [SUCCESS] DEEPSEEK_API_KEY is present.
)

echo.
echo [INFO] Starting FastAPI server on port %BACKEND_PORT% (listening on all local IPs)...
echo [INFO] Logs will also be written to %BACKEND_LOG_FILE%
echo.
cd backend
if not exist "logs" mkdir logs
echo [INFO] Backend process starting...
echo [INFO] Open http://127.0.0.1:%BACKEND_PORT%/health in a browser to verify.
uvicorn main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload --log-level debug 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%BACKEND_LOG_FILE%' -Append"

pause
