@echo off
setlocal
cd /d "%~dp0backend"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)

if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 ( echo Could not create the virtual environment. & pause & exit /b 1 )
)
call venv\Scripts\activate.bat

echo Installing packages (first run only takes a minute)...
pip install -q -r requirements.txt
if errorlevel 1 ( echo Package install failed. Check your internet connection. & pause & exit /b 1 )

if not exist "..\frontend\dist\index.html" (
  echo The built dashboard is missing. Run "npm install" then "npm run build" inside the frontend folder.
  pause
  exit /b 1
)

echo.
echo Starting Outage Command Center at http://localhost:8000
echo Press Ctrl+C in this window to stop it.
start "" http://localhost:8000
python -m uvicorn app.main:app --port 8000
pause
