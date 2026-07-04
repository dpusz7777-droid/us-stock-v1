@echo off
setlocal EnableExtensions

cd /d "%~dp0\.."

echo === US Stock AI - Windows setup ===
echo Project: %CD%

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher py was not found.
  echo Please install Python 3.12 or 3.13 from https://www.python.org/downloads/windows/
  echo Make sure "Add python.exe to PATH" is checked.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
  )
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo Installing requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed to install requirements.
  pause
  exit /b 1
)

if not exist reports mkdir reports
if not exist logs mkdir logs

echo.
echo Setup complete.
echo Next: double click windows\run_full_once.bat
pause
