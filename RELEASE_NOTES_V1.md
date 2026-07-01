# RELEASE_NOTES_V1

## 1. V1 功能列表

- AI 驱动的美股日报与盘前/盘后简报
- 只读持仓管理与监控
- 个股分析与 F-score 排序
- 市场看盘仪表板
- 观察名单管理
- Windows 自动调度脚本：`run_morning.bat`、`run_full_once.bat`、`create_scheduled_tasks.bat`
- 报告索引管理：`reports/index.json`
- 系统健康检查与 run_guard 重复执行保护
- 本地报告保存与报告索引记录

## 2. 三天稳定性测试结果

- 2026-06-24：Windows 全量自动运行完成，但 morning 缺失，问题已定位为 Windows 侧文件同步丢失而非代码保存逻辑故障。
- 2026-06-25：自动运行正常，`2026-06-25-morning.md` 与索引一致。
- 2026-06-26：`2026-06-26-morning` 索引存在，文件在当前 Mac 工作区缺失，确认为同步问题。
- 当前项目测试结果：`tests/test_briefing.py` 和 `tests/test_report_index.py` 共 23 项通过。

## 3. 已修复的问题

- 修复 `run_full_once.bat` 与 `run_morning.bat` 的 fallback 不一致：
  - 当 `DEEPSEEK_API_KEY` 缺失时，`run_full_once.bat` 现在会与 `run_morning.bat` 一致地设置 `USSTOCKAI_MORNING_FALLBACK=1`，保证在 AI 生成失败时触发本地 fallback morning 报告保存。

## 4. 已知限制

- `V1` 仍依赖 Windows 任务计划和本地文件同步机制，报告文件同步需额外保证。当前问题主要来源于 Windows → Mac / Git 同步流程，而非 `main.py` 逻辑。
- `DEEPSEEK_API_KEY` 不可用时，morning 报告使用本地 fallback 模式生成，不包含 AI 原生分析输出。
- `reports/index.json` 仅记录本地报告元数据，不能自动修复丢失的 Markdown 文件。
- 目前 `run_guard` 仅基于 `reports/index.json` 判断重复运行，不校验实际文件存在性。

## 5. V2 开发计划

- 增加报告文件与索引一致性校验，防止“索引存在但文件缺失”场景。
- 增强 Windows 自动任务日志与文件同步可观测性。
- 补充 `run_guard` 文件级校验，确保同一天执行记录与实际文件一致。
- 支持跨平台调度与同步自动恢复机制。
- 进一步完善 `main.py` 的命令行帮助与异常日志输出。
