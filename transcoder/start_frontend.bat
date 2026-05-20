@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "FRONTEND_DIR=%SCRIPT_DIR%frontend"

cd /d "%FRONTEND_DIR%"

where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm not found. Install Node.js 18+ and add it to PATH.
    pause & exit /b 1
)

if not exist "node_modules\" (
    echo Installing frontend dependencies...
    npm install
)

echo Starting Transcoder Frontend on port 3000...
npm run dev
pause
