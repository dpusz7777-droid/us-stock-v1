$ErrorActionPreference = 'Stop'

$source = [System.IO.Path]::GetFullPath('C:\Users\Administrator\AppData\Local\NVIDIA\DXCache')
$target = [System.IO.Path]::GetFullPath('E:\缓存\NVIDIA\DXCache')
$logPath = 'E:\美股研究文件夹\维护\缓存维护日志.txt'

function Write-Log {
    param([string]$Message)
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [NVIDIA] $Message"
}

try {
    if (-not $source.StartsWith('C:\Users\Administrator\AppData\Local\NVIDIA\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw '源路径安全检查失败'
    }
    if (-not $target.StartsWith('E:\缓存\NVIDIA\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw '目标路径安全检查失败'
    }

    if (Test-Path -LiteralPath $source) {
        $item = Get-Item -LiteralPath $source -Force
        if ($item.LinkType -eq 'Junction') {
            Write-Log 'DXCache 已经是目录联接，无需处理。'
            exit 0
        }
    }

    # DXCache 是可重建的显卡着色器缓存，无需复制旧内容。
    if (Test-Path -LiteralPath $source) {
        Remove-Item -LiteralPath $source -Recurse -Force
    }
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }

    [System.IO.Directory]::CreateDirectory($target) | Out-Null
    New-Item -ItemType Junction -Path $source -Target $target | Out-Null

    $link = Get-Item -LiteralPath $source -Force
    if ($link.LinkType -ne 'Junction') {
        throw '目录联接验证失败'
    }

    Write-Log "迁移完成：$source -> $target"
} catch {
    Write-Log "本次未完成，将在下次开机重试：$($_.Exception.Message)"
}

# 清理已完成迁移后遗留的 WPS 旧备份。只有联接目标验证正确时才删除。
$kingsoftLink = 'C:\Users\Administrator\AppData\Local\Kingsoft'
$kingsoftTarget = 'E:\应用数据\Local\Kingsoft'
$kingsoftBackup = 'C:\Users\Administrator\AppData\Local\Kingsoft.__migration_backup'

try {
    if (Test-Path -LiteralPath $kingsoftBackup) {
        $link = Get-Item -LiteralPath $kingsoftLink -Force
        if ($link.LinkType -ne 'Junction' -or @($link.Target) -notcontains $kingsoftTarget) {
            throw 'WPS 联接验证失败，保留旧备份。'
        }
        Remove-Item -LiteralPath $kingsoftBackup -Recurse -Force
        Write-Log '已删除 WPS 迁移旧备份。'
    }
} catch {
    Write-Log "WPS 旧备份本次未清理，将在下次开机重试：$($_.Exception.Message)"
}
