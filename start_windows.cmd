@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.11+ is required. Download it from https://www.python.org/downloads/
        echo Select "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)
echo Installing the preview server dependencies...
%PYTHON% -m pip install -e "%~dp0backend"
if errorlevel 1 (
    echo Dependencies could not be installed.
    pause
    exit /b 1
)
echo.
%PYTHON% "%~dp0preview_server.py"
if errorlevel 1 pause
endlocal
