@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0\.."

if not exist logs mkdir logs
set "LOG_FILE=logs\windows_automation.log"
set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo.>> "%LOG_FILE%"
echo [%DATE% %TIME%] === Full one-click run start ===>> "%LOG_FILE%"
echo === Full one-click run start ===

echo [1/4] morning --save
if "%DEEPSEEK_API_KEY%"=="" (
  echo [WARN] DEEPSEEK_API_KEY is not set. Enabling local morning fallback.>> "%LOG_FILE%"
  echo [WARN] DEEPSEEK_API_KEY is not set. Enabling local morning fallback.
  set "USSTOCKAI_MORNING_FALLBACK=1"
) else (
  set "USSTOCKAI_MORNING_FALLBACK="
)
"%PYTHON_EXE%" main.py morning --save >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo [WARN] morning exited with errorlevel %ERRORLEVEL%.

set "LATEST_EXCEL="
for /f "delims=" %%F in ('dir /b /a-d /o-d "position-information-*.xlsx" 2^>nul') do (
  set "LATEST_EXCEL=%%F"
  goto :excel_found
)

:excel_found
if defined LATEST_EXCEL (
  echo [2/4] sync-usmart !LATEST_EXCEL!
  echo [%DATE% %TIME%] sync-usmart !LATEST_EXCEL!>> "%LOG_FILE%"
  "%PYTHON_EXE%" main.py sync-usmart --excel "!LATEST_EXCEL!" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 echo [WARN] sync-usmart exited with errorlevel %ERRORLEVEL%.
) else (
  echo [2/4] [WARN] No position-information-*.xlsx found. Skip sync-usmart.
  echo [%DATE% %TIME%] [WARN] No position-information-*.xlsx found. Skip sync-usmart.>> "%LOG_FILE%"
)

echo [3/4] doctor --skip-tests
"%PYTHON_EXE%" main.py doctor --skip-tests >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo [WARN] doctor exited with errorlevel %ERRORLEVEL%.

echo [4/4] evening --save
"%PYTHON_EXE%" main.py evening --save >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo [WARN] evening exited with errorlevel %ERRORLEVEL%.

echo [%DATE% %TIME%] === Full one-click run done ===>> "%LOG_FILE%"
echo Done. See %LOG_FILE%
pause
exit /b 0
