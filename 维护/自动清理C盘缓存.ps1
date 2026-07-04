$ErrorActionPreference = 'SilentlyContinue'

$cutoff = (Get-Date).AddDays(-14)
$logPath = 'E:\美股研究文件夹\维护\缓存维护日志.txt'
$roots = @(
    'C:\Users\Administrator\AppData\Local\Temp',
    'C:\Windows\Temp',
    'C:\Users\Administrator\AppData\Local\CrashDumps',
    'E:\缓存\Temp'
)
$allowedRoots = @(
    [System.IO.Path]::GetFullPath('C:\Users\Administrator\AppData\Local\Temp'),
    [System.IO.Path]::GetFullPath('C:\Windows\Temp'),
    [System.IO.Path]::GetFullPath('C:\Users\Administrator\AppData\Local\CrashDumps'),
    [System.IO.Path]::GetFullPath('E:\缓存\Temp')
)

$before = 0L
$after = 0L

foreach ($root in $roots) {
    $resolved = [System.IO.Path]::GetFullPath($root)
    if ($allowedRoots -notcontains $resolved) {
        continue
    }
    if (-not (Test-Path -LiteralPath $resolved)) {
        continue
    }

    $before += (Get-ChildItem -LiteralPath $resolved -Force -Recurse -File |
        Measure-Object -Property Length -Sum).Sum

    Get-ChildItem -LiteralPath $resolved -Force -Recurse -File |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        Remove-Item -Force

    Get-ChildItem -LiteralPath $resolved -Force -Recurse -Directory |
        Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force) } |
        Remove-Item -Force

    $after += (Get-ChildItem -LiteralPath $resolved -Force -Recurse -File |
        Measure-Object -Property Length -Sum).Sum
}

$freedGB = [math]::Round(($before - $after) / 1GB, 3)
$message = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [每周清理] 释放 " + $freedGB + " GB"
Add-Content -LiteralPath $logPath -Encoding UTF8 -Value $message
