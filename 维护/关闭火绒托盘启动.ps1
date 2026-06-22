$ErrorActionPreference = 'SilentlyContinue'

# 火绒核心服务 HipsDaemon 保持运行；这里只禁用托盘 hipstray。
Start-Sleep -Seconds 20

$approvedPath = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run64'
New-Item -Path $approvedPath -Force | Out-Null

# 03 表示已由用户禁用，后续 8 字节为时间信息；全零同样可被 Windows 识别。
[byte[]]$disabledValue = 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
New-ItemProperty -LiteralPath $approvedPath -Name 'sysdiag' -Value $disabledValue -PropertyType Binary -Force | Out-Null

Get-Process -Name 'hipstray' -ErrorAction SilentlyContinue | Stop-Process -Force
