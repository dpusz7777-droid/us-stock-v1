@echo off
setlocal EnableExtensions

cd /d "%~dp0\.."

if not exist logs mkdir logs
set "LOG_FILE=logs\windows_automation.log"
set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo.>> "%LOG_FILE%"
echo [%DATE% %TIME%] === Evening automation start ===>> "%LOG_FILE%"
echo === Evening automation start ===

echo [1/2] evening --save
"%PYTHON_EXE%" main.py evening --save >> "%LOG_FILE%" 2>&1
set "EVENING_EXIT=%ERRORLEVEL%"
if not "%EVENING_EXIT%"=="0" (
  echo [ERROR] evening exited with errorlevel %EVENING_EXIT%.
  echo [%DATE% %TIME%] [ERROR] evening exited with errorlevel %EVENING_EXIT%.>> "%LOG_FILE%"
)

echo [2/2] doctor --skip-tests
"%PYTHON_EXE%" main.py doctor --skip-tests >> "%LOG_FILE%" 2>&1
set "DOCTOR_EXIT=%ERRORLEVEL%"
if not "%DOCTOR_EXIT%"=="0" (
  echo [WARN] doctor exited with errorlevel %DOCTOR_EXIT%.
  echo [%DATE% %TIME%] [WARN] doctor exited with errorlevel %DOCTOR_EXIT%.>> "%LOG_FILE%"
)

echo [%DATE% %TIME%] === Evening automation done ===>> "%LOG_FILE%"
echo Done. See %LOG_FILE%
exit /b 0
