@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================
:: 北极星每日决策报告 — Windows 定时任务入口脚本
:: 自动路径：E:\桌面路径\美股V1
:: 本脚本可被 Windows 任务计划程序调用
:: ============================================================

set "PROJECT_DIR=E:\桌面路径\美股V1"
set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\daily_decision_task.log"

:: 自动创建 logs 目录
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: 写入开始时间戳
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "YYYY=!datetime:~0,4!"
set "MM=!datetime:~4,2!"
set "DD=!datetime:~6,2!"
set "HH=!datetime:~8,2!"
set "MIN=!datetime:~10,2!"
set "SS=!datetime:~12,2!"
set "TIMESTAMP=!YYYY!-!MM!-!DD! !HH!:!MIN!:!SS!"

echo. >> "%LOG_FILE%"
echo ===== 北极星每日决策报告任务开始：%TIMESTAMP% ===== >> "%LOG_FILE%"

:: 切换到项目目录
cd /d "%PROJECT_DIR%"

:: 运行报告生成脚本
python scripts/run_daily_decision_report.py >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

:: 写入结束时间戳和退出码
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "YYYY=!datetime:~0,4!"
set "MM=!datetime:~4,2!"
set "DD=!datetime:~6,2!"
set "HH=!datetime:~8,2!"
set "MIN=!datetime:~10,2!"
set "SS=!datetime:~12,2!"
set "TIMESTAMP=!YYYY!-!MM!-!DD! !HH!:!MIN!:!SS!"

echo ===== 北极星每日决策报告任务结束：%TIMESTAMP%，退出码：%EXIT_CODE% ===== >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

exit /b %EXIT_CODE%