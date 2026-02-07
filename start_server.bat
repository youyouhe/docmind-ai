@echo off
REM PageIndex API Server Startup Script for Windows
REM This script properly handles Ctrl+C to clean up processes

cd /d "%~dp0"

REM Set default port if not specified
if "%PORT%"=="" set PORT=8003

echo Loading environment variables from .env...
if exist .env (
    for /f "tokens=*" %%a in ('type .env ^| findstr /v "^#"') do (
        set %%a
    )
    echo Environment variables loaded.
)

echo Starting PageIndex API server...
echo Port: %PORT%
echo.
echo Press Ctrl+C to stop the server
echo.

REM Start server
python -m uvicorn api.index:app --host 0.0.0.0 --port %PORT% --reload

REM Cleanup on exit
echo.
echo Server stopped.
