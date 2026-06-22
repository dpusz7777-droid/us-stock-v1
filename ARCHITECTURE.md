# 系统架构（ARCHITECTURE）

> 最后更新: 2026-06-23

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────┐
│                     main.py                          │
│            统一入口 · 子命令路由                      │
├────────────┬───────────┬───────────┬────────────────┤
│ dashboard  │ analyze   │ portfolio │ monitor/watch  │
│ 看盘       │ 个股分析   │ 持仓管理   │ 监控/观察名单  │
└─────┬──────┴─────┬─────┴─────┬─────┴──────┬─────────┘
      │            │           │            │
      ▼            ▼           ▼            ▼
 market_     stock_      portfolio_      monitor.py
 dashboard   analyzer    service/       (只读看板)
 .py         .py         tracker.py
                                              │
                                     ┌────────┴────────┐
                                     │ portfolio_service│
                                     │ .py              │
                                     │ (核心只读服务)    │
                                     └─────────────────┘
```

---

## 二、核心模块职责

### 2.1 `main.py` — 统一入口

- 使用 `argparse` 解析子命令
- 将请求转发到对应模块
- `portfolio` 子命令直接调用 `portfolio_service`（不通过子进程）
- 其他子命令通过 `subprocess` 调用独立脚本
- `init` 命令自动安装基础依赖

### 2.2 `portfolio_service.py` — Schema 1.1 核心服务

**定位**: 持仓数据的唯一事实来源计算引擎。

**职责**:
- 加载并校验 Schema 1.1 JSON 文件
- 从 `transactions` 运行时重建持仓（shares、cost_basis、avg_cost）
- 计算已实现盈亏和现金变化
- 应用外部行情计算未实现盈亏
- 不访问网络、不写入文件

**关键数据结构**:
- `PortfolioState` — 完整的运行时持仓快照（不可变 dataclass）
- `PositionState` — 单只股票运行时持仓（不可变 dataclass）

**核心函数**:
| 函数 | 作用 |
|------|------|
| `load_portfolio()` | 加载 JSON 文件，解析为 Decimal |
| `validate_portfolio()` | 校验 Schema 版本、字段完整性、类型规则 |
| `build_portfolio_state()` | 从 transactions 重建运行时持仓 |
| `apply_market_prices()` | 应用外部行情数据 |
| `get_portfolio_snapshot()` | 一站式只读入口 |

### 2.3 `portfolio_tracker.py` — 持仓只读报告

- 继承旧版 `portfolio_tracker` 名称但功能缩减为只读
- 调用 `portfolio_service` 获取数据
- 输出格式化的持仓报告
- 阻断所有旧写入参数（--add、--sell、--sync、--config）

### 2.4 `monitor.py` — 持仓监控看板

- 旧版包含完整的买入/卖出/导入/初始化功能
- 第一阶段：仅保留只读看板功能
- 阻断所有旧写入参数（--add、--sell、--import-usmart、--init）
- 旧版写入函数（`cmd_buy`、`cmd_sell` 等）保留源码但禁用

### 2.5 `market_dashboard.py` — 每日看盘

- 获取大盘指数（纳斯达克、道指、标普、VIX、罗素）
- 获取热门观察股行情
- 快速/完整模式切换
- 板块轮动分析

### 2.6 `stock_analyzer.py` — 个股分析

- 七维度评分系统（估值、盈利能力、成长性、财务健康、动量、机构情绪、流动性）
- F-score 排序
- 观察名单管理

### 2.7 `short_trade.py` — 短线分析

- 技术面信号分析
- 支撑阻力位计算
- 仓位建议

---

## 三、数据流

### 3.1 持仓只读流程

```
portfolio.json (Schema 1.1)
        │
        ▼
load_portfolio() ───→ JSON → Decimal 解析
        │
        ▼
validate_portfolio() ───→ Schema/字段校验
        │
        ▼
build_portfolio_state() ───→ transactions 排序 → 逐条处理 → PortfolioState
        │
        ▼
apply_market_prices() (可选) ───→ 注入行情 → 计算市值/未实现盈亏
        │
        ▼
CLI 输出 / 看板显示
```

### 3.2 每日看盘流程

```
yfinance API
    │
    ├──→ 大盘指数 (INDEX_TICKERS)
    ├──→ 热门观察股 (WATCH_TICKERS)
    │
    ▼
格式化输出 → 涨跌幅、成交量、日内变动
```

### 3.3 个股分析流程

```
yfinance API
    │
    ▼
fetch_stock_data() → 基本面数据
    │
    ▼
七维度评分计算
    │
    ▼
输出评分报告 + 交易建议
```

---

## 四、Schema 1.1 数据格式

### 持久化 JSON 结构

```
根级
├── schema_version          # "1.1"
├── account
│   ├── account_id
│   ├── account_name
│   ├── broker
│   ├── base_currency       # "USD"
│   ├── cash_status         # "known" | "unknown"
│   ├── created_at
│   └── updated_at
├── settings
│   ├── stop_loss_pct       # 8.0
│   ├── target_profit_pct   # 25.0
│   └── max_single_position_pct  # 20.0
└── transactions[]
    ├── transaction_id      # 唯一编号
    ├── external_id         # 券商编号 / null
    ├── transaction_type    # OPENING_POSITION | BUY | SELL
    ├── symbol              # 股票代码
    ├── shares              # 股数
    ├── price               # 每股价格
    ├── amount              # 入金/出金金额 (买卖为 null)
    ├── fees                # 手续费
    ├── executed_at         # 成交时间 / null
    ├── effective_at        # 生效时间 (OPENING_POSITION)
    ├── recorded_at         # 记录时间
    ├── source              # manual | usmart_ocr | usmart_api | legacy_migration
    └── note                # 备注
```

### 运行时不持久化字段

- `positions`、`cash`、`avg_cost`、`cost_basis`
- `market_value`、`realized_pnl`、`unrealized_pnl`
- `total_equity`、`buying_power`
- 全部在运行时从 `transactions` + 行情计算

详见 `docs/portfolio_schema.md`。

---

## 五、交易类型与计算

### 当前支持的交易类型

| 类型 | 说明 | 现金影响 | 持仓影响 |
|------|------|----------|----------|
| `OPENING_POSITION` | 期初持仓（迁移） | 无 | 增加股数、成本 |
| `BUY` | 买入 | 减少 | 增加股数、成本（含手续费） |
| `SELL` | 卖出 | 增加 | 减少股数、实现盈亏 |

### 计算规则

- **成本法**: 移动加权平均
- **精度**: decimal.Decimal（金融计算精度）
- **排序**: effective_at/executed_at → recorded_at → transaction_id
- **现金 unknown**: cash/total_equity/buying_power 为 null

---

## 六、测试架构

```
tests/
├── test_main.py                   # 4 tests — main.py 持仓概览接入
├── test_portfolio_service.py      # 16 tests — 核心计算逻辑
├── test_portfolio_tracker.py      # 17 tests — 只读报告、边界条件
└── test_monitor.py                # 6 tests — 只读看板、旧命令封锁
```

### 测试原则

- 使用内存数据，不访问网络
- 不读取/修改项目中的 JSON 文件
- 使用临时目录隔离文件操作
- `setUp`/`tearDown` 逐字节核对项目 JSON 文件未变
- 通过 `unittest.mock.patch` 阻断网络和写入函数

---

## 七、安全边界

1. 不自动执行真实交易
2. 所有真实交易必须人工确认
3. 不连接券商 API 自动下单
4. API Key 使用 `.env`，不上传 Git
5. 持仓 JSON 不保存运行时计算结果（避免多个真相来源）
6. 旧写入参数在第一阶段全部拒绝

---

## 八、未来架构演进

### Phase 2：行情适配层

```
                    price_provider.py
                    ├── yfinance 适配器
                    ├── 缓存层 (TTL)
                    └── 统一行情接口
                            │
                            ▼
              apply_market_prices(state, prices)
```

### Phase 3：交易写入

```
                    transaction_writer.py
                    ├── BUY 校验与写入
                    ├── SELL 校验与写入
                    ├── DEPOSIT/WITHDRAWAL
                    └── 乐观锁并发控制