@echo off
title 北极星一键启动器

echo ============================
echo      北极星系统启动中...
echo ============================

cd /d %~dp0

echo.
echo [1/3] 检查Python环境...
python --version

echo.
echo [2/3] 检测是否已在运行...
if exist northstar.lock (
    echo.
    echo WARNING: 检测到 northstar.lock 文件，北极星可能已在运行。
    echo 如需强制启动，请先删除 northstar.lock 文件。
    echo.
    choice /C YN /M "仍然继续启动？"
    if errorlevel 2 exit /b 1
)

echo.
echo [3/3] 通过 launch.py 启动（含单例守卫 + 浏览器保护）...
python launch.py

echo.
echo 系统已退出。
pause
