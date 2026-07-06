<#
.SYNOPSIS
  安装北极星每日决策报告 Windows 任务计划程序任务。
.DESCRIPTION
  创建一个名为"北极星每日决策报告"的计划任务，每天北京时间 20:45 自动运行。
  运行脚本：scripts/windows/run_daily_decision_report.bat
.NOTES
  如果同名任务已存在，会先删除再重新创建（覆盖更新）。
#>

$TaskName = "北极星每日决策报告"
$ProjectDir = "E:\桌面路径\美股V1"
$BatchScript = Join-Path $ProjectDir "scripts\windows\run_daily_decision_report.bat"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  安装北极星每日决策报告定时任务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查项目目录
if (-not (Test-Path $ProjectDir)) {
    Write-Host "[错误] 项目目录不存在: $ProjectDir" -ForegroundColor Red
    exit 1
}

# 检查 bat 脚本
if (-not (Test-Path $BatchScript)) {
    Write-Host "[错误] 启动脚本不存在: $BatchScript" -ForegroundColor Red
    exit 1
}

# 检查已有任务
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "[提示] 已存在同名任务：" $TaskName -ForegroundColor Yellow
    Write-Host "       将先删除旧任务，再创建新任务。" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[已删除] 旧任务已删除" -ForegroundColor Green
}

# 创建任务执行动作
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchScript`"" `
    -WorkingDirectory $ProjectDir

# 触发器：每天 20:45，北京时间（UTC+8 → UTC 12:45）
$Trigger = New-ScheduledTaskTrigger -Daily -At "12:45"
$Trigger.Enabled = $true

# 设置：失败重试 3 次，每次间隔 5 分钟
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -Hidden:$false `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# 创建原则：使用当前登录用户
$Principal = New-ScheduledTaskPrincipal `
    -UserId "INTERACTIVE" `
    -LogonType S4U `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Force

    Write-Host ""
    Write-Host "[成功] 任务安装完成！" -ForegroundColor Green
    Write-Host ""
    Write-Host "  任务名称：$TaskName" -ForegroundColor White
    Write-Host "  运行时间：每天 20:45（北京时间）" -ForegroundColor White
    Write-Host "  执行脚本：$BatchScript" -ForegroundColor White
    Write-Host "  日志文件：$ProjectDir\logs\daily_decision_task.log" -ForegroundColor White
    Write-Host ""
    Write-Host "  提示：如果 20:45 电脑关机，任务不会运行。" -ForegroundColor Yellow
    Write-Host "       如果 20:45 电脑睡眠但插着电源，会唤醒运行。" -ForegroundColor Yellow
    Write-Host "       运行日志请查看上面的日志文件。" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  手动测试运行：" -ForegroundColor Cyan
    Write-Host "    powershell -ExecutionPolicy Bypass scripts\windows\check_daily_decision_task.ps1" -ForegroundColor Gray
    Write-Host ""

} catch {
    Write-Host "[错误] 创建任务失败: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  可能原因：需要以管理员权限运行此脚本。" -ForegroundColor Yellow
    Write-Host "  请尝试：右键 PowerShell → 以管理员身份运行" -ForegroundColor Yellow
    exit 1
}