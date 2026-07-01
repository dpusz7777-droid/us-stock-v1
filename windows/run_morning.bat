@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0\.."

if not exist logs mkdir logs
set "LOG_FILE=logs\windows_automation.log"
set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo.>> "%LOG_FILE%"
echo [%DATE% %TIME%] === Morning automation start ===>> "%LOG_FILE%"
echo === Morning automation start ===

if "%DEEPSEEK_API_KEY%"=="" (
  echo [WARN] DEEPSEEK_API_KEY is not set. Enabling local morning fallback.>> "%LOG_FILE%"
  echo [WARN] DEEPSEEK_API_KEY is not set. Enabling local morning fallback.
  set "USSTOCKAI_MORNING_FALLBACK=1"
) else (
  set "USSTOCKAI_MORNING_FALLBACK="
)

echo [1/2] morning --save
"%PYTHON_EXE%" main.py morning --save >> "%LOG_FILE%" 2>&1
set "MORNING_EXIT=%ERRORLEVEL%"
if not "%MORNING_EXIT%"=="0" (
  echo [ERROR] morning exited with errorlevel %MORNING_EXIT%.
  echo [%DATE% %TIME%] [ERROR] morning exited with errorlevel %MORNING_EXIT%.>> "%LOG_FILE%"
)

echo [2/2] doctor --skip-tests
"%PYTHON_EXE%" main.py doctor --skip-tests >> "%LOG_FILE%" 2>&1
set "DOCTOR_EXIT=%ERRORLEVEL%"
if not "%DOCTOR_EXIT%"=="0" (
  echo [WARN] doctor exited with errorlevel %DOCTOR_EXIT%.
  echo [%DATE% %TIME%] [WARN] doctor exited with errorlevel %DOCTOR_EXIT%.>> "%LOG_FILE%"
)

echo [%DATE% %TIME%] === Morning automation done ===>> "%LOG_FILE%"
echo Done. See %LOG_FILE%
exit /b 0
