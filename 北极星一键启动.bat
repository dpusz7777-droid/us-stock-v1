@echo off
chcp 65001 >nul
title 北极星 UI - 关闭此窗口即可关闭系统
cd /d "%~dp0"

echo.
echo ==========================================
echo        北极星 UI 一键启动器
echo        地址：http://localhost:8501
echo        关闭本窗口即可关闭系统
echo ==========================================
echo.

if not exist "northstar\ui\dashboard.py" (
    echo [错误] 未找到 northstar\ui\dashboard.py
    echo 当前目录：
    cd
    pause
    exit /b 1
)

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE=.venv\Scripts\python.exe
)

echo [1/4] 检查 Python...
%PYTHON_EXE% --version
if errorlevel 1 (
    echo [错误] Python 不可用。
    pause
    exit /b 1
)

echo.
echo [2/4] 检查 Streamlit...
%PYTHON_EXE% -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo [错误] 当前 Python 环境没有安装 streamlit。
    echo 请让开发代理修复依赖，不要让用户手动处理。
    pause
    exit /b 1
)

echo.
echo [3/4] 清理旧的 8501 端口进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    echo 正在关闭旧进程 PID: %%a
    taskkill /PID %%a /F >nul 2>nul
)

echo.
echo [4/4] 启动北极星 UI...
echo 浏览器稍后会自动打开：http://localhost:8501
echo 关闭本窗口即可关闭系统。
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 6; Start-Process 'http://localhost:8501'"

%PYTHON_EXE% -m streamlit run "northstar\ui\dashboard.py" --server.port 8501 --server.headless true --browser.gatherUsageStats false

echo.
echo 北极星 UI 已停止。
pause