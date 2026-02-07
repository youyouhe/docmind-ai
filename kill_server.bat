@echo off
REM Kill all Python processes on the specified port

set PORT=8003

echo Checking for processes on port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%.*LISTENING"') do (
    echo Killing process %%a
    taskkill /F /PID %%a 2>nul
)

echo Cleanup complete.
