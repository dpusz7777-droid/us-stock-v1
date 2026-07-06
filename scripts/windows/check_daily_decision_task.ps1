<#
.SYNOPSIS
  检查北极星每日决策报告任务状态。
.DESCRIPTION
  输出任务是否存在、下一次运行时间、上一次运行时间、上一次运行结果、任务状态等。
#>

$TaskName = "北极星每日决策报告"
$LogFile = "E:\桌面路径\美股V1\logs\daily_decision_task.log"
$ReportDir = "E:\桌面路径\美股V1\reports\daily_decision"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  北极星每日决策报告 — 任务检查" -ForegroundColor Cyan
Write-Host ""
Write-Host "  任务名称：$TaskName" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 任务是否存在
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Write-Host "[1] 任务状态：✅ 已安装" -ForegroundColor Green
    Write-Host "    状态：$($Task.State)"
    Write-Host "    描述：$($Task.Description)"
    Write-Host ""
} else {
    Write-Host "[1] 任务状态：❌ 未安装" -ForegroundColor Red
    Write-Host "    如需安装，请运行：" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass scripts\windows\install_daily_decision_task.ps1" -ForegroundColor Gray
    Write-Host ""
}

# 2. 下一次运行时间
$Triggers = $Task | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
if ($Triggers) {
    $NextRun = $Triggers.NextRunTime
    if ($NextRun -and $NextRun -ne [DateTime]::MaxValue) {
        Write-Host "[2] 下一次运行时间：" -ForegroundColor White
        $BeijingTime = $NextRun.ToLocalTime()
        Write-Host "    $($BeijingTime.ToString('yyyy-MM-dd HH:mm:ss'))（北京时间）" -ForegroundColor Green
    } else {
        Write-Host "[2] 下一次运行时间：无（可能已过期）" -ForegroundColor Yellow
    }

    $LastRun = $Triggers.LastRunTime
    if ($LastRun -and $LastRun -ne [DateTime]::MinValue) {
        Write-Host ""
        Write-Host "[3] 上一次运行时间：" -ForegroundColor White
        $LastBeijing = $LastRun.ToLocalTime()
        Write-Host "    $($LastBeijing.ToString('yyyy-MM-dd HH:mm:ss'))（北京时间）" -ForegroundColor Cyan

        $LastResult = $Triggers.LastTaskResult
        if ($LastResult -eq 0) {
            Write-Host "    上一次运行结果：✅ 成功（退出码 0）" -ForegroundColor Green
        } else {
            Write-Host "    上一次运行结果：❌ 失败（退出码 $LastResult）" -ForegroundColor Red
        }
    } else {
        Write-Host ""
        Write-Host "[3] 上一次运行时间：从未运行" -ForegroundColor Yellow
    }
}

# 3. 日志文件
Write-Host ""
if (Test-Path $LogFile) {
    $LogSize = (Get-Item $LogFile).Length
    $LogSizeFormatted = if ($LogSize -gt 1KB) { "{0:N1} KB" -f ($LogSize / 1KB) } else { "$LogSize 字节" }
    Write-Host "[4] 运行日志：" -ForegroundColor White
    Write-Host "    $LogFile" -ForegroundColor Gray
    Write-Host "    文件大小：$LogSizeFormatted" -ForegroundColor Gray

    # 显示最后 5 行
    Write-Host ""
    Write-Host "    最近日志（最后 5 行）：" -ForegroundColor White
    Get-Content $LogFile -Tail 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
} else {
    Write-Host "[4] 运行日志：文件不存在" -ForegroundColor Yellow
    Write-Host "    $LogFile" -ForegroundColor Gray
    Write-Host "    任务至少需要手动执行一次后才会生成。" -ForegroundColor Gray
}

# 4. 最近报告
Write-Host ""
$LatestReport = Get-ChildItem -Path $ReportDir -Filter "daily_decision_*.md" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($LatestReport) {
    Write-Host "[5] 最新报告：" -ForegroundColor White
    Write-Host "    $($LatestReport.FullName)" -ForegroundColor Gray
    Write-Host "    生成时间：$($LatestReport.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Gray
} else {
    Write-Host "[5] 最新报告：尚未生成" -ForegroundColor Yellow
    Write-Host "    报告目录：$ReportDir" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  如需帮助，请查看：" -ForegroundColor Cyan
Write-Host "  docs/windows_daily_decision_task.md" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""