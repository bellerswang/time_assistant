@echo off
title ChronoAI Backend Launcher
echo ===================================================
echo   ChronoAI Smart Time Assistant - Backend Launcher
echo ===================================================
echo.

cd /d "%~dp0"

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

echo.
echo [INFO] Starting FastAPI server on port 11337 (listening on all local IPs)...
echo.
cd backend
uvicorn main:app --host 0.0.0.0 --port 11337 --reload

pause
