@echo off
title TikTok Scheduler
cd /d "%~dp0"

echo ===================================================
echo   TikTok Scheduler - Launcher
echo ===================================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Run setup to check / install dependencies
echo [*] Checking dependencies...
python setup.py
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency setup failed. See errors above.
    pause
    exit /b 1
)

echo.
echo [*] Starting TikTok Scheduler...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with an error.
    pause
    exit /b 1
)
