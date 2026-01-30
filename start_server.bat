@echo off
REM PageIndex API Server Startup Script for Windows
REM This script loads environment variables from .env before starting the server

REM Enable delayed expansion for variable handling
setlocal EnableDelayedExpansion

REM Get script directory and change to it
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Initialize variables with defaults
set "LLM_PROVIDER=deepseek"
set "LLM_MODEL="
set "PORT=8003"
set "PAGEINDEX_DB_PATH=data/documents.db"
set "HAS_API_KEY=0"

REM Load environment variables from .env if it exists
if exist ".env" (
    echo Loading environment variables from .env...

    REM Parse .env file line by line
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        set "key=%%a"
        set "value=%%b"

        REM Skip comments (lines starting with #)
        echo !key! | findstr /b "#" >nul
        if errorlevel 1 (
            REM Skip empty lines
            if not "!key!"=="" (
                REM Set environment variable
                set "!key!=!value!"

                REM Check for API keys
                if /i "!key!"=="DEEPSEEK_API_KEY" set "HAS_API_KEY=1"
                if /i "!key!"=="OPENAI_API_KEY" set "HAS_API_KEY=1"
                if /i "!key!"=="GEMINI_API_KEY" set "HAS_API_KEY=1"
                if /i "!key!"=="OPENROUTER_API_KEY" set "HAS_API_KEY=1"
                if /i "!key!"=="ZHIPU_API_KEY" set "HAS_API_KEY=1"
            )
        )
    )

    echo Environment variables loaded.
    echo.
    echo === Environment Variables ===
    echo LLM_PROVIDER=!LLM_PROVIDER!
    echo LLM_MODEL=!LLM_MODEL!
    echo PORT=!PORT!
    echo PAGEINDEX_DB_PATH=!PAGEINDEX_DB_PATH!
    echo.
    echo API Keys:
    call :show_masked_key "DEEPSEEK_API_KEY"
    call :show_masked_key "OPENAI_API_KEY"
    call :show_masked_key "GEMINI_API_KEY"
    call :show_masked_key "OPENROUTER_API_KEY"
    call :show_masked_key "ZHIPU_API_KEY"
    echo =============================
    echo.
) else (
    echo Warning: .env file not found!
    echo.
)

REM Check if at least one API key is configured
if "!HAS_API_KEY!"=="0" (
    echo Error: No API key found. Please set DEEPSEEK_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, or ZHIPU_API_KEY in .env
    pause
    exit /b 1
)

REM Set default port
if not defined PORT set "PORT=8003"

REM Start the server
echo Starting PageIndex API server...
echo Port: !PORT!
echo.
python -m uvicorn api.index:app --host 0.0.0.0 --port !PORT! --reload

endlocal
exit /b

REM ============================================================================
REM Subroutine to display masked API key
REM ============================================================================
:show_masked_key
set "KEY_NAME=%~1"
set "KEY_VALUE=!%KEY_NAME%!"

if not defined KEY_VALUE (
    echo   %KEY_NAME%=(not set)
) else (
    set "MASKED=!KEY_VALUE:~0,8!"
    if "!MASKED!"=="!KEY_VALUE!" (
        echo   %KEY_NAME%=***
    ) else (
        echo   %KEY_NAME%=!MASKED!***
    )
)
exit /b
