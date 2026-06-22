# 📊 AI 美股研究与监控系统

AI 驱动的美股投资研究辅助工具，提供股票分析、持仓管理、市场监控等功能。

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 看盘
python main.py dashboard

# 3. 分析个股
python main.py analyze NVDA

# 4. 查看持仓
python main.py portfolio

# 5. F-score 排序观察股
python main.py rank
```

---

## 功能概览

### 每日看盘

查看大盘指数、热门股行情、板块轮动。

```bash
python main.py dashboard           # 完整看盘
python main.py dashboard --quick   # 快速扫一眼
python main.py dashboard --sector  # 板块表现
```

### 个股分析

多维评分系统（估值、盈利能力、成长性、财务健康、动量、机构情绪、流动性）。

```bash
python main.py analyze AAPL            # 单只分析
python main.py analyze AAPL MSFT NVDA  # 批量分析
python main.py rank                    # F-score 排序观察股
```

### 持仓管理（只读）

基于 Schema 1.1 `transactions` 运行时重建的只读持仓服务，不连接网络、不修改数据。

```bash
python main.py portfolio              # 查看持仓概览
python main.py portfolio --portfolio-file portfolio_migrated_candidate.json
```

### 持仓监控看板

```bash
python main.py monitor                # 只读持仓看板
python main.py monitor --daily        # 每日简报
python main.py monitor --alert        # 只看预警
```

### 观察名单管理

```bash
python main.py watchlist               # 列出观察名单
python main.py watchlist --add AAPL    # 添加股票
python main.py watchlist --remove AAPL # 移除股票
```

### 其他独立工具

```bash
python short_trade.py PLTR          # 短线技术面分析
python 美股筛选器.py                 # 股票条件筛选
```

---

## 系统架构

```
main.py                    # 统一入口（子命令路由）
├── market_dashboard.py    # 每日看盘仪表盘
├── stock_analyzer.py      # 个股深度分析引擎
├── portfolio_service.py   # Schema 1.1 只读持仓服务
├── portfolio_tracker.py   # 持仓只读报告 CLI
├── monitor.py             # 持仓只读监控看板
├── short_trade.py         # 短线技术面分析
├── 美股筛选器.py           # 条件筛选工具
├── 抓取机器人.py           # 自动化数据抓取
├── docs/                  # 文档
│   └── portfolio_schema.md  # 持仓数据格式规范
├── tests/                 # 测试
│   ├── test_main.py
│   ├── test_portfolio_service.py
│   ├── test_portfolio_tracker.py
│   └── test_monitor.py
└── tools/                 # 工具
    └── migrate_portfolio_v1.py  # 旧数据迁移
```

---

## 测试

```bash
python -m pytest tests/ -v
```

所有测试使用内存数据，不访问网络，不修改项目文件。

---

## 项目文档

| 文档 | 内容 |
|------|------|
| `PROJECT_CONTEXT.md` | 项目目标、开发原则、分工、安全边界 |
| `PROJECT_STATUS.md` | 当前状态、模块结构、测试结果、下一步路线 |
| `ARCHITECTURE.md` | 架构设计、模块职责、关键流程 |
| `docs/portfolio_schema.md` | Schema 1.1 统一持仓数据格式规范 |
| `USER_PROFILE.md` | 用户背景和使用偏好 |

---

## 技术栈

- **语言**: Python 3.10+
- **数据**: yfinance、pandas、numpy
- **测试**: pytest/unittest
- **精度**: decimal.Decimal（金融计算）
- **持仓格式**: JSON（Schema 1.1 标准）

---

## 当前阶段：Schema 1.1 第一阶段

**只读持仓服务** — 基于 transactions 运行时重建持仓，不访问网络、不连接券商。

### 第一阶段规则

- ✅ 不访问网络
- ✅ 不连接券商
- ✅ 不修改真实持仓文件
- ✅ 旧写入参数（--add、--sell、--sync 等）全部拒绝

### 下一步

1. 行情适配层（price_provider.py）
2. 实时行情注入持仓报告
3. 价格预警
4. 交易录入迁移到 transactions 模式

详见 `PROJECT_STATUS.md`。

---

## 安全声明

- 本系统不自动执行真实交易
- 所有真实交易必须人工确认
- API Key 不会硬编码在代码中
- 不连接券商 API 自动下单