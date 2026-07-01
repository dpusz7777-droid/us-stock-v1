# Windows PC 自动运行说明

目标：Windows PC 是唯一自动运行机器，Mac 只用于开发和代码更新。

## 1. 当前系统是否支持 Windows

支持。

- Python 代码使用标准库和跨平台依赖，`main.py` 可以在 Windows 直接运行。
- uSMART Excel 导入使用 Python 标准库读取 `.xlsx`，不依赖 Excel 软件，也不需要安装 Microsoft Office。
- Yahoo Finance 行情通过 `yfinance`，Windows 可用。
- 测试使用 `unittest`，不需要额外测试框架。

建议 Windows 安装：

- Python 3.12 或 3.13
- Git 可选；如果不会用 Git，可以直接复制整个项目文件夹到 PC。

`requirements.txt` 已包含当前运行所需依赖：

- `yfinance`
- `pandas`
- `numpy`
- `pyautogui`
- `Pillow`

AI 简报如果要调用 DeepSeek，需要在 Windows 设置环境变量 `DEEPSEEK_API_KEY`。
没有 API Key 时，程序会输出错误提示，不会交易，也不会修改外部账户。

## 2. 文件放置规则

把整个项目文件夹复制到 Windows PC，例如：

```text
C:\USStockAI
```

uSMART Excel 文件放在项目根目录，文件名保持：

```text
position-information-20260623.xlsx
position-information-*.xlsx
```

自动脚本会读取最新的 `position-information-*.xlsx`。
如果找不到 Excel，脚本只提示缺失并跳过同步，不会崩溃。

## 3. 第一次安装

在 Windows 上进入项目文件夹，双击：

```text
windows\setup_pc.bat
```

它会自动：

- 创建 `.venv`
- 安装 `requirements.txt`
- 创建 `reports` 和 `logs` 目录

如果提示找不到 Python，请安装 Python，并勾选：

```text
Add python.exe to PATH
```

## 4. 一键运行完整流程

双击：

```text
windows\run_full_once.bat
```

它会依次执行：

1. `python main.py morning --save`
2. 自动寻找最新 `position-information-*.xlsx`
3. `python main.py sync-usmart --excel <最新Excel>`
4. `python main.py doctor --skip-tests`
5. `python main.py evening --save`

运行日志在：

```text
logs\windows_automation.log
```

系统日志在：

```text
logs\system.log
```

报告保存在：

```text
reports\
```

## 5. 每天自动运行

双击：

```text
windows\create_scheduled_tasks.bat
```

如果失败，请右键选择：

```text
Run as administrator
```

它会创建两个 Windows 任务计划：

```text
USStockAI Morning 2030
每天 20:30 执行 windows\run_morning.bat

USStockAI Evening 0430
每天 04:30 执行 windows\run_evening.bat
```

盘前任务执行：

1. `morning --save`
2. 自动同步最新 uSMART Excel
3. `doctor --skip-tests`

盘后任务执行：

1. `evening --save`
2. `doctor --skip-tests`

## 6. Mac 和 PC 数据同步规则

重要规则：

- PC 是唯一自动运行机器。
- Mac 只做开发，不运行定时任务。
- Mac 不要同时执行 `sync-usmart`、`morning --save`、`evening --save`。
- uSMART Excel 只放到 PC 的项目根目录，由 PC 自动读取。
- PC 运行三天测试期间，以 PC 生成的 `reports`、`logs`、`portfolio_migrated_candidate.json` 为准。

推荐流程：

1. Mac 开发代码。
2. 测试通过后，把代码同步到 PC。
3. PC 执行自动任务。
4. 三天后，把 PC 上的 `reports` 和 `logs` 拿回 Mac 分析。

## 7. 安全边界

当前自动运行方案保证：

- 不自动交易。
- 不连接券商 API。
- 不修改券商账户。
- 只读取本地 Excel、本地 JSON、Yahoo Finance 行情和新闻。
- `sync-usmart` 只更新本地 JSON 和本地报告。

## 8. 如何确认已经成功运行

第一步，双击：

```text
windows\run_full_once.bat
```

确认看到：

```text
Done. See logs\windows_automation.log
```

第二步，打开日志：

```text
logs\windows_automation.log
```

确认包含：

```text
Morning automation
sync-usmart
System Doctor
Evening automation
```

第三步，检查报告目录：

```text
reports\
```

确认新增了：

```text
YYYY-MM-DD-morning.md
YYYY-MM-DD-evening.md
YYYY-MM-DD-sync.md
```

第四步，检查任务计划程序：

```text
Task Scheduler
```

确认存在：

```text
USStockAI Morning 2030
USStockAI Evening 0430
```

第五步，三天测试期间每天检查：

- `logs\windows_automation.log` 有当天记录
- `reports\index.json` 有当天报告索引
- `portfolio_migrated_candidate.json` 时间和持仓正常

## 9. 三天自动运行测试建议

第 1 天：

- 双击 `setup_pc.bat`
- 双击 `run_full_once.bat`
- 双击或管理员运行 `create_scheduled_tasks.bat`

第 2 天：

- 只检查日志和报告，不手动运行 Mac 定时任务。

第 3 天：

- 检查是否连续生成报告。
- 运行：

```text
.venv\Scripts\python.exe main.py doctor --skip-tests
```

如果 doctor 只出现 warning，没有 FAIL，即可认为 PC 自动运行链路正常。
