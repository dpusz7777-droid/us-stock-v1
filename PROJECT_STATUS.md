# 项目状态（PROJECT_STATUS）

> 最后更新: 2026-06-23

---

## 一、当前阶段

**Schema 1.1 第一阶段 — 只读持仓服务**

核心模块已实现基于 `transactions` 运行时重建持仓的只读架构，不访问网络、不连接券商、不修改真实持仓文件。

---

## 二、模块结构

| 模块 | 职责 | 状态 |
|------|------|------|
| `main.py` | 统一入口，子命令路由 | ✅ 稳定 |
| `portfolio_service.py` | Schema 1.1 只读加载、校验、持仓计算、行情应用 | ✅ 稳定 |
| `portfolio_tracker.py` | Schema 1.1 持仓只读报告（CLI） | ✅ 稳定 |
| `monitor.py` | Schema 1.1 持仓只读看板 + 旧版写入命令封锁 | ✅ 稳定 |
| `market_dashboard.py` | 每日看盘（大盘指数、热门股） | ✅ 可用 |
| `stock_analyzer.py` | 个股多维度评分分析 | ✅ 可用 |
| `short_trade.py` | 短线技术面分析 | ✅ 可用 |
| `美股筛选器.py` | 股票条件筛选（输出 CSV/Excel） | ✅ 可用 |
| `抓取机器人.py` | 自动化数据抓取（uSMART 等） | ⚠️ 依赖 pyautogui 和 GUI |
| `deepseek_print_time.py` | 简易时间打印工具 | ✅ 可用 |

### 测试模块（`tests/`）

| 测试文件 | 覆盖目标 | 状态 |
|----------|----------|------|
| `test_main.py` | main.py 持仓概览接入 | ✅ 4 tests |
| `test_portfolio_service.py` | portfolio_service 核心逻辑（校验、计算、行情） | ✅ 16 tests |
| `test_portfolio_tracker.py` | portfolio_tracker 只读报告、边界条件 | ✅ 17 tests |
| `test_monitor.py` | monitor 只读看板、旧命令封锁 | ✅ 6 tests |

### 工具模块（`tools/`）

| 工具 | 用途 |
|------|------|
| `tools/migrate_portfolio_v1.py` | 旧版持仓 JSON 到 Schema 1.1 迁移工具 |
| `tools/PROJECT_STATUS.md` | 旧版项目状态（保留中） |

### 文档模块（`docs/`）

| 文档 | 用途 |
|------|------|
| `docs/portfolio_schema.md` | Schema 1.1 统一持仓数据格式完整规范 |

---

## 三、测试结果

```
43 passed
27 subtests passed
```

### 测试覆盖的关键场景

- **portfolio_service**:
  - 期初持仓正确重建（shares、avg_cost、cost_basis）
  - 未知现金不伪装成 0（cash、total_equity、buying_power = null）
  - 已知现金正确计算
  - 买入加权平均成本 + 手续费计入
  - 部分卖出和全部卖出的已实现盈亏
  - 卖出超持仓拒绝
  - 不支持的交易类型明确报错
  - 交易按时间排序
  - Decimal 小数精度保持
  - 输入文档不被修改
  - 行情价格应用（市值、未实现盈亏、精度）

- **main.py**:
  - 持仓概览输出（summary + positions）
  - 不访问网络、不调子进程
  - 文件缺失友好报错
  - 旧写入参数（--add/--sell/--sync/--config）阻断

- **portfolio_tracker / monitor**:
  - 候选文件正确解析
  - 旧版 Schema 清晰不兼容提示
  - 旧写入参数全部阻断
  - JSON 文件逐字节不变
  - 各种边界条件（空文件、无效 JSON、缺失字段、空持仓、无效符号）

---

## 四、当前规则（第一阶段）

- ✅ 不访问网络（不调用 yfinance 等外部 API）
- ✅ 不连接券商（不调用任何券商 API）
- ✅ 不修改真实持仓文件（不写入 portfolio.json 等持久化文件）
- ✅ 旧写入参数（--add、--sell、--sync、--config、--import-usmart、--init）全部拒绝

---

## 五、下一步开发路线

### 短期（Phase 2 — 行情适配层）

- [ ] 设计 `price_provider.py` — 行情获取与缓存适配层
- [ ] 构建行情适配层，支持 yfinance 和未来其他数据源
- [ ] 将实时行情注入只读持仓报告（unrealized_pnl、market_value）
- [ ] 实现价格预警（止损、止盈、日内涨跌幅）

### 中期（Phase 3 — 交易录入迁移）

- [ ] 将旧写入逻辑迁移到 transactions 模式
- [ ] 支持 BUY、SELL、DEPOSIT、WITHDRAWAL 交易类型
- [ ] 实现交易校验和确认流程

### 长期

- [ ] 支持更多交易类型（DIVIDEND、TAX、SPLIT、ADJUSTMENT）
- [ ] 券商 API 接入（uSMART API）
- [ ] Telegram/其他渠道推送
- [ ] 图形界面
- [ ] 多币种支持

---

## 六、已知问题

- `抓取机器人.py` 依赖 pyautogui，需要图形界面环境，无法在纯 CLI 或 CI 中运行
- `short_trade.py` 的 watchlist 使用独立文件 `short_watchlist.json`，与 `stock_analyzer.py` 的 `watchlist.json` 不共享
- `portfolio.json`（旧版快照结构）和 `portfolio_migrated_candidate.json`（Schema 1.1）同时存在，旧版结构逐渐淘汰
- `market_dashboard.py` 和 `stock_analyzer.py` 均直接调用 yfinance，没有统一的数据获取层