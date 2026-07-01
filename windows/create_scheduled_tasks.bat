@echo off
setlocal EnableExtensions

cd /d "%~dp0\.."

set "PROJECT_DIR=%CD%"
set "MORNING_SCRIPT=%PROJECT_DIR%\windows\run_morning.bat"
set "EVENING_SCRIPT=%PROJECT_DIR%\windows\run_evening.bat"

echo === Create Windows scheduled tasks ===
echo Project: %PROJECT_DIR%
echo.

if not exist "%MORNING_SCRIPT%" (
  echo [ERROR] Missing %MORNING_SCRIPT%
  pause
  exit /b 1
)

if not exist "%EVENING_SCRIPT%" (
  echo [ERROR] Missing %EVENING_SCRIPT%
  pause
  exit /b 1
)

schtasks /Create /TN "USStockAI Morning 2030" /SC DAILY /ST 20:30 /TR "%MORNING_SCRIPT%" /F
if errorlevel 1 (
  echo [ERROR] Failed to create morning task.
  echo Try right-clicking this file and choose "Run as administrator".
  pause
  exit /b 1
)

schtasks /Create /TN "USStockAI Evening 0430" /SC DAILY /ST 04:30 /TR "%EVENING_SCRIPT%" /F
if errorlevel 1 (
  echo [ERROR] Failed to create evening task.
  echo Try right-clicking this file and choose "Run as administrator".
  pause
  exit /b 1
)

echo.
echo Scheduled tasks created:
echo - USStockAI Morning 2030: daily 20:30
echo - USStockAI Evening 0430: daily 04:30
echo.
echo Morning task details:
schtasks /Query /TN "USStockAI Morning 2030" /V /FO LIST
echo.
echo Evening task details:
schtasks /Query /TN "USStockAI Evening 0430" /V /FO LIST
echo.
echo Logs will be written to logs\windows_automation.log
pause
