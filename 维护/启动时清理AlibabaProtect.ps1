$ErrorActionPreference = 'SilentlyContinue'

$taskName = 'Codex-Cleanup-AlibabaProtect'
$installDir = [System.IO.Path]::GetFullPath('C:\Program Files (x86)\AlibabaProtect')
$driverFile = [System.IO.Path]::GetFullPath('C:\Windows\System32\drivers\AliPaladinEx64.sys')
$logPath = 'E:\美股研究文件夹\维护\安全软件清理日志.txt'

function Write-Log {
    param([string]$Message)
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [AlibabaProtect] $Message"
}

try {
    Get-Process -Name 'AlibabaProtect' -ErrorAction SilentlyContinue | Stop-Process -Force
    sc.exe delete AlibabaProtect | Out-Null
    sc.exe delete AliPaladin | Out-Null

    if ($installDir.StartsWith('C:\Program Files (x86)\', [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $installDir)) {
        Remove-Item -LiteralPath $installDir -Recurse -Force
    }

    if ($driverFile -eq 'C:\Windows\System32\drivers\AliPaladinEx64.sys' -and
        (Test-Path -LiteralPath $driverFile)) {
        Remove-Item -LiteralPath $driverFile -Force
    }

    $serviceLeft = Get-Service -Name 'AlibabaProtect' -ErrorAction SilentlyContinue
    $driverLeft = Test-Path -LiteralPath $driverFile
    $folderLeft = Test-Path -LiteralPath $installDir

    if (-not $serviceLeft -and -not $driverLeft -and -not $folderLeft) {
        Write-Log '残留清理完成。'
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    } else {
        Write-Log "仍有残留，将在下次开机重试。服务=$([bool]$serviceLeft)，驱动=$driverLeft，目录=$folderLeft"
    }
} catch {
    Write-Log "清理失败，将在下次开机重试：$($_.Exception.Message)"
}

