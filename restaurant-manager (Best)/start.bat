@echo off
echo ==========================================
echo   RESTAURANT MANAGER - Starting...
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed!
    echo Please download Python from https://python.org
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

REM Install required packages
echo Installing required packages...
pip install -r requirements.txt

REM Start the application
echo.
echo Starting Restaurant Manager...
echo Open your browser and go to: http://127.0.0.1:5000
echo.
echo Press CTRL+C to stop the server
echo ==========================================
python app.py

pause
