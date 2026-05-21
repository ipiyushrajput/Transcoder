@echo off
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%backend"
set "VENV=%BACKEND_DIR%\.venv"

REM Trusted-host flags bypass SSL certificate errors from corporate proxies
set "PIP_TRUSTED=--trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org"

cd /d "%BACKEND_DIR%"

REM Locate Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and add it to PATH.
    pause & exit /b 1
)

REM Create venv if not present
if not exist "%VENV%\" (
    echo Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause & exit /b 1
    )
)

REM Always install / sync requirements
echo Installing requirements...
"%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip %PIP_TRUSTED%
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt %PIP_TRUSTED%
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed. See output above.
    pause & exit /b 1
)

echo Starting Transcoder Backend on port 5001...
"%VENV%\Scripts\python.exe" app.py
pause
