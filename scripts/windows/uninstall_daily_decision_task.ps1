<#
.SYNOPSIS
  卸载北极星每日决策报告 Windows 任务计划程序任务。
.DESCRIPTION
  删除名为"北极星每日决策报告"的计划任务。
  如果任务不存在，不会报错。
#>

$TaskName = "北极星每日决策报告"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  卸载北极星每日决策报告定时任务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Existing) {
    Write-Host "[提示] 任务不存在，无需卸载。" -ForegroundColor Yellow
    Write-Host "       任务名称：$TaskName" -ForegroundColor Gray
    exit 0
}

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[成功] 任务已卸载：$TaskName" -ForegroundColor Green
    Write-Host "       之后不再自动生成每日决策报告。" -ForegroundColor Gray
} catch {
    Write-Host "[错误] 卸载失败: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  可能原因：需要以管理员权限运行此脚本。" -ForegroundColor Yellow
    Write-Host "  请尝试：右键 PowerShell → 以管理员身份运行" -ForegroundColor Yellow
    exit 1
}