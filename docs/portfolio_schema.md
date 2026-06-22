# 统一持仓数据格式（第一版）

## 1. 文档目的与核心原则

本文档定义 AI 美股研究与监控系统第一版统一持仓数据格式，供手工录入、盈立 OCR 导入和未来盈立 API 导入共同使用。

第一版采用以下原则：

1. `transactions`（已确认交易记录）是现金、持仓、成本和盈亏的唯一事实来源。
2. `positions`、`cash`、`summary`、成本、市值和盈亏全部在运行时计算，不写入持久化 JSON。
3. 第一版只使用美元（USD），暂不处理汇率和多币种。
4. 所有时间统一转换为 UTC，并使用 ISO 8601 格式。
5. OCR 结果必须经过用户确认，不能把识别结果直接当成正式交易。
6. 成本计算统一采用移动加权平均成本法。

这样可以避免现金、持仓和交易记录各自保存一套数值，形成多个互相冲突的“真相来源”。

## 2. 第一版持久化结构

持久化 JSON 只保存以下四部分：

```text
根级
├── schema_version
├── account
│   ├── account_id
│   ├── account_name
│   ├── broker
│   ├── base_currency
│   ├── cash_status
│   ├── created_at
│   └── updated_at
├── settings
│   ├── stop_loss_pct
│   ├── target_profit_pct
│   └── max_single_position_pct
└── transactions[]
    ├── transaction_id
    ├── external_id
    ├── transaction_type
    ├── symbol
    ├── shares
    ├── price
    ├── amount
    ├── fees
    ├── executed_at
    ├── effective_at
    ├── recorded_at
    ├── source
    └── note
```

### 2.1 不持久化的运行时字段

以下字段由系统根据交易和最新行情临时计算，不写入本文件定义的持久化 JSON：

- `cash`
- `positions`
- `avg_cost`
- `cost_basis`
- `cost_basis_sold`
- `market_value`
- `realized_pnl`
- `unrealized_pnl`
- `unrealized_pnl_pct`
- `total_equity`
- `summary`

运行时可以生成这些字段用于看板和报告，但不得把它们作为第二套长期数据来源。行情缓存如果以后需要保存，应使用独立文件，不得混入交易事实数据。

## 3. 字段定义与来源

### 3.1 用户输入或外部导入字段

| 位置 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `account` | `account_id` | string | 本地账户唯一编号 |
| `account` | `account_name` | string | 账户显示名称 |
| `account` | `broker` | string | 券商名称；手工账户可写 `manual` |
| `settings` | `stop_loss_pct` | number | 默认止损百分比 |
| `settings` | `target_profit_pct` | number | 默认止盈百分比 |
| `settings` | `max_single_position_pct` | number | 单只股票最大仓位百分比 |
| `transactions` | `transaction_type` | string | 已定义的交易或迁移事件类型 |
| `transactions` | `symbol` | string/null | 股票代码；入金和出金时为 `null` |
| `transactions` | `shares` | number/null | 成交股数；入金和出金时为 `null` |
| `transactions` | `price` | number/null | 每股成交价；入金和出金时为 `null` |
| `transactions` | `amount` | number/null | 入金或出金金额；买卖股票时为 `null` |
| `transactions` | `fees` | number | 手续费，没有时填写 `0.0` |
| `transactions` | `executed_at` | string | 实际成交或资金变动时间 |
| `transactions` | `effective_at` | string/null | `OPENING_POSITION` 的系统追踪生效时间；其他类型为 `null` |
| `transactions` | `source` | string | `manual`、`usmart_ocr`、`usmart_api` 或 `legacy_migration` |
| `transactions` | `external_id` | string/null | 券商唯一编号；没有时为 `null` |
| `transactions` | `note` | string | 可选备注，没有时使用空字符串 |

### 3.2 系统生成字段

| 位置 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 根级 | `schema_version` | string | 数据格式版本，本版为 `1.1` |
| `account` | `base_currency` | string | 第一版固定为 `USD` |
| `account` | `cash_status` | string | 现金基线状态：`known` 或 `unknown` |
| `account` | `created_at` | string | 账户创建时间 |
| `account` | `updated_at` | string | 文件最近更新时间 |
| `transactions` | `transaction_id` | string | 本地生成的唯一交易编号 |
| `transactions` | `recorded_at` | string | 交易写入本地系统的时间 |

系统计算字段不能由用户直接填写。用户如果需要纠正持仓或现金，应修改错误交易或补充一笔经过确认的正式交易，不能直接修改计算结果。所有期初资金和后续入金都必须记录为 `DEPOSIT`，账户层不再保存另一份期初资金。

## 4. 各类交易的字段规则

所有正式交易对象必须包含完整的统一字段。无业务含义的字段使用 `null`，不能省略，也不能用 `0` 伪装成未知值。

### 4.1 BUY（买入）

| 字段 | 规则 |
|---|---|
| `symbol` | 必填，大写股票代码 |
| `shares` | 必填，必须大于 0 |
| `price` | 必填，必须大于 0 |
| `amount` | 必须为 `null` |
| `fees` | 必填，必须大于或等于 0 |
| `executed_at` | 必填 |

### 4.2 SELL（卖出）

| 字段 | 规则 |
|---|---|
| `symbol` | 必填，大写股票代码 |
| `shares` | 必填，必须大于 0，且不能超过成交前持股数 |
| `price` | 必填，必须大于 0 |
| `amount` | 必须为 `null` |
| `fees` | 必填，必须大于或等于 0 |
| `executed_at` | 必填 |

### 4.3 DEPOSIT（入金）

| 字段 | 规则 |
|---|---|
| `symbol` | 必须为 `null` |
| `shares` | 必须为 `null` |
| `price` | 必须为 `null` |
| `amount` | 必填，必须大于 0 |
| `fees` | 第一版必须为 `0.0` |
| `executed_at` | 必填 |

### 4.4 WITHDRAWAL（出金）

| 字段 | 规则 |
|---|---|
| `symbol` | 必须为 `null` |
| `shares` | 必须为 `null` |
| `price` | 必须为 `null` |
| `amount` | 必填，必须大于 0，且不能超过出金前可用现金 |
| `fees` | 第一版必须为 `0.0` |
| `executed_at` | 必填 |

### 4.5 OPENING_POSITION（期初持仓）

`OPENING_POSITION` 只表示系统启用前已经真实存在、但缺少完整逐笔成交历史的持仓。它是迁移事件，不是 BUY，也不代表券商原始成交记录。

| 字段 | 规则 |
|---|---|
| `symbol` | 必填，大写股票代码 |
| `shares` | 必填，必须大于 0；运行时增加对应持股数 |
| `price` | 必填，必须大于 0；表示人工确认的期初每股平均成本 |
| `amount` | 必须为 `null` |
| `fees` | 必须为 `0.0` |
| `executed_at` | 必须为 `null`，不得使用迁移时间冒充真实成交时间 |
| `effective_at` | 必填，使用系统开始追踪该持仓的 UTC 时间 |
| `source` | 必须为 `legacy_migration` |
| `note` | 必须说明来自真实持仓快照，且不代表原始逐笔成交历史 |

运行时计算：

```text
新增 shares = OPENING_POSITION.shares
新增 cost_basis = shares × price
avg_cost = cost_basis ÷ shares
cash 变化 = 0
realized_pnl_since_tracking 初始值 = 0
```

这里的已实现盈亏只表示系统追踪开始后的结果，不代表账户历史累计盈亏。

使用限制：

- 只有专用旧数据迁移工具可以生成 `OPENING_POSITION`。
- `manual`、`usmart_ocr`、`usmart_api` 禁止创建该类型。
- 日常交易录入界面和普通 API 导入流程禁止提供该类型。

### 4.6 未来预留交易类型

以下类型是未来版本必须区分的真实账户事件，第一版仅定义含义，暂不实现计算：

| 类型 | 含义 | 重要规则 |
|---|---|---|
| `DIVIDEND` | 股票现金分红 | 不得使用 `DEPOSIT` 代替，否则会把投资收益误认为外部入金 |
| `TAX` | 分红预扣税或其他税费 | 不得使用普通交易手续费或 `WITHDRAWAL` 模糊代替 |
| `SPLIT` | 股票拆股或并股 | 会改变股数和每股成本，但不改变拆股时的总成本 |
| `ADJUSTMENT` | 经人工核实的券商账户调整 | 必须注明原因，不能用于掩盖无法解释的差额 |

第一版程序如果读取到以上任一未支持类型，必须：

1. 立即停止该账户的现金、持仓、成本和盈亏计算。
2. 明确输出交易编号、交易类型和“不支持该交易类型”的错误提示。
3. 不得跳过该记录后继续生成看似完整的结果。
4. 不得自动把它转换成 `DEPOSIT`、`WITHDRAWAL`、`BUY` 或 `SELL`。
5. 等待支持该类型的新版程序或经过明确设计的数据迁移流程。

## 5. 币种与时间规范

### 5.1 币种

- `account.base_currency` 第一版固定为 `USD`。
- `price`、`amount`、`fees`、成本、市值、现金和盈亏全部表示美元。
- JSON 中金额只保存数字，例如 `1500.25`，不保存 `$`、逗号或“美元”等文字。
- 第一版不进行人民币、港币或新加坡元换算。
- 如果未来支持多币种，必须升级 `schema_version`，并明确原币金额和汇率，不能改变第一版字段含义。

### 5.2 时间

- 所有时间必须是合法的 ISO 8601 UTC 时间。
- 第一版统一格式为 `YYYY-MM-DDTHH:MM:SSZ`。
- 示例：`2026-06-22T14:30:00Z`。
- `executed_at` 表示真实成交或资金变动时间。
- `recorded_at` 表示写入本地系统的时间。
- `created_at` 和 `updated_at` 分别表示账户建立和数据文件更新时间。
- 不允许使用没有时区的信息，例如 `2026-06-22 14:30:00`。
- 无法确认真实成交时间时，记录不得进入正式交易列表，应先等待用户确认。

## 6. 现金、成本与盈亏计算口径

第一版采用移动加权平均成本法，并按 `executed_at` 从早到晚处理交易。同一秒存在多笔交易时，按它们在 `transactions` 数组中的顺序处理。

### 6.1 现金

只有 `account.cash_status="known"` 时，系统才允许计算和显示绝对现金余额。

```text
cash_status = known：
  初始 cash = 0，并根据完整资金与交易记录累计

cash_status = unknown：
  cash = null
  只能计算系统启用后的 cash_change，不能计算绝对现金

BUY：
cash -= shares × price + fees

SELL：
cash += shares × price - fees

DEPOSIT：
cash += amount

WITHDRAWAL：
cash -= amount

OPENING_POSITION：
cash 不变
```

当 `cash_status="known"` 时，账户启用时的全部初始资金必须由可靠资金记录建立，后续真实入金使用 `DEPOSIT`。任何交易执行后都不允许 `cash < 0`。

当 `cash_status="unknown"` 时：

- 不得把现金默认当作 0；
- `cash`、`total_equity` 和 `buying_power` 必须为 `null`；
- 不得显示误导性的完整账户净值或总资产；
- 必须提示用户通过券商 API、对账单或人工确认建立可靠现金基线；
- 持仓数量、持仓成本、当前市值和未实现盈亏仍可独立计算。

第一版不支持融资、保证金或做空。

### 6.2 买入与平均成本

```text
买入总支出 = shares × price + fees
新 cost_basis = 原 cost_basis + 买入总支出
新 shares = 原 shares + 买入 shares
新 avg_cost = 新 cost_basis ÷ 新 shares
```

买入手续费计入持仓成本。

### 6.3 卖出与已实现盈亏

```text
cost_basis_sold = 卖出 shares × 卖出前 avg_cost
卖出净收入 = 卖出 shares × price - fees
本次 realized_pnl = 卖出净收入 - cost_basis_sold
剩余 shares = 原 shares - 卖出 shares
剩余 cost_basis = 原 cost_basis - cost_basis_sold
```

部分卖出后 `avg_cost` 保持不变。全部卖出后，该股票的剩余股数和剩余成本都归零，不再出现在运行时 `positions` 中；历史交易仍然保留。

账户或股票累计 `realized_pnl` 等于相关 SELL 交易运行时已实现盈亏之和。

### 6.4 当前市值与未实现盈亏

行情数据必须提供 `last_price` 和对应的 `price_as_of`，它们属于运行时行情输入，不写入持久化交易 JSON。

```text
market_value = shares × last_price
unrealized_pnl = market_value - cost_basis
unrealized_pnl_pct = unrealized_pnl ÷ cost_basis × 100
cash_status = known 时：
total_equity = cash + 所有持仓 market_value 之和

cash_status = unknown 时：
total_equity = null
```

如果任一持仓缺少有效的 `last_price` 或 `price_as_of`：

- 该持仓的 `market_value`、`unrealized_pnl` 和 `unrealized_pnl_pct` 为 `null`；
- 账户级 `market_value`、`unrealized_pnl` 和 `total_equity` 也必须为 `null`；
- 运行时报告应显示 `prices_complete = false`，不能把部分市值伪装成完整总额。

## 7. 通用校验规则

### 7.1 唯一性与枚举

- `schema_version` 本版必须等于字符串 `1.1`。
- `transaction_id` 必须是非空字符串，并在当前账户内唯一。
- 非空的 `external_id` 必须与 `source` 组合后唯一，防止 API 重复导入。
- 文档定义的 `transaction_type` 包括 `BUY`、`SELL`、`DEPOSIT`、`WITHDRAWAL`、`OPENING_POSITION`、`DIVIDEND`、`TAX`、`SPLIT`、`ADJUSTMENT`。
- 本版实现前五种；遇到后四种必须按 4.6 节停止相关计算，不能静默忽略。
- `OPENING_POSITION` 的 `source` 必须为 `legacy_migration`；其他来源使用该类型属于校验错误。
- `source` 只能是 `manual`、`usmart_ocr`、`usmart_api`、`legacy_migration`。
- `legacy_migration` 只允许用于旧版持仓数据迁移生成的初始化交易，不得用于用户日常手工录入、OCR 导入或 API 同步。

### 7.2 股票代码

- `symbol` 必须去除首尾空格并转换为大写。
- 第一版允许大写英文字母、数字、点和短横线，例如 `BRK.B`、`BF-B`。
- 买卖交易不能使用空字符串或 `null`。

### 7.3 数值

- `shares` 必须是有限数字且大于 0；禁止 `NaN`、无穷大、字符串和负数。
- `price` 在买卖交易中必须是有限数字且大于 0。
- `amount` 在入金和出金交易中必须是有限数字且大于 0。
- `fees` 必须是有限数字且大于或等于 0。
- `stop_loss_pct`、`target_profit_pct` 和 `max_single_position_pct` 使用百分数，例如 `8.0` 表示 8%。
- 三个百分比字段必须大于 0 且小于或等于 100。
- 计算时保留足够精度，不在每一步提前四舍五入；仅在界面显示时按需要保留小数。

### 7.4 时间与顺序

- 所有 `*_at` 字段必须符合 `YYYY-MM-DDTHH:MM:SSZ`。
- `OPENING_POSITION.executed_at` 是唯一例外，必须为 `null`；其 `effective_at` 必须符合 UTC ISO 8601 格式。
- BUY、SELL、DEPOSIT 和 WITHDRAWAL 的 `effective_at` 必须为 `null`。
- `recorded_at` 不得早于系统已知的实际写入时刻。
- 处理交易时以 `executed_at` 为主要顺序，数组顺序作为同一时间的次要顺序。

## 8. 数据来源兼容规则

### 8.1 手工录入

- `source` 使用 `manual`。
- 用户确认交易类型、代码、股数、成交价、手续费和成交时间后，才能写入正式交易列表。
- `external_id` 可以为 `null`。

### 8.2 盈立 OCR

- `source` 使用 `usmart_ocr`。
- OCR 原始结果不属于正式交易记录，必须在导入流程中暂存并等待用户确认。
- 只有股票代码或持仓金额时，不能推算真实成交价、股数、手续费或成交时间，也不能生成正式 BUY 交易。
- 用户补全并确认所有必填字段后，才能转换成与手工录入相同的正式交易对象。
- 第一版持久化 JSON 不保存未确认 OCR 结果；OCR 原始结果应留在独立导入文件中。

### 8.3 未来盈立 API

- `source` 使用 `usmart_api`。
- `external_id` 必须保存 API 返回的唯一成交编号。
- 导入前使用 `source + external_id` 检查是否已经存在，避免重复交易。
- API 原始字段必须先转换成本文档规定的统一字段，其他模块不能直接依赖券商字段名称。

### 8.4 旧数据迁移

- `source` 使用 `legacy_migration`。
- 该来源只表示交易由受控迁移工具根据旧版持仓快照生成，不代表券商原始成交记录。
- 迁移交易必须在 `note` 中说明无法恢复的历史信息、采用的假设和时间来源。
- 普通录入程序不得提供 `legacy_migration` 选项；只有专用迁移工具可以生成该来源。
- 迁移候选文件必须经过校验和人工确认，不能自动替换正式数据。

## 9. schema_version 与版本升级规则

`schema_version` 用来告诉程序当前文件遵循哪一套字段和计算规则。版本号改变时，旧字段的含义不能被静默改写。

必须遵守以下升级流程：

1. **迁移前备份**：先完整备份原始数据文件，备份文件不得在迁移过程中覆盖。
2. **按版本选择逻辑**：程序读取 `schema_version`，只能调用对应起始版本到目标版本的明确迁移逻辑。
3. **拒绝未知版本**：缺少版本号或版本不受支持时，程序必须拒绝加载并显示清晰错误，不能猜测字段含义。
4. **生成新文件**：迁移结果必须写入新的候选文件，不能直接覆盖原文件。
5. **完整验证**：检查 JSON 语法、必填字段、交易编号唯一性、交易顺序、现金非负、卖出不超持仓及计算结果。
6. **人工替换**：只有验证成功并由用户确认后，才能用候选文件人工替换正式文件。
7. **保留审计信息**：迁移记录应注明原版本、目标版本、迁移时间和验证结果。

本版文件的 `schema_version` 固定为字符串 `1.1`。旧版 `1.0` 文件必须经过迁移和人工确认，不能静默按 `1.1` 解释。

## 10. 已校验的持久化 JSON 示例

下面是缺少可靠现金基线时的迁移候选示例。它只建立人工确认的期初持仓，不伪造 DEPOSIT 或真实成交历史。

```json
{
  "schema_version": "1.1",
  "account": {
    "account_id": "account_001",
    "account_name": "盈立美股账户",
    "broker": "uSMART",
    "base_currency": "USD",
    "cash_status": "unknown",
    "created_at": "2026-06-15T01:55:00Z",
    "updated_at": "2026-06-22T14:30:00Z"
  },
  "settings": {
    "stop_loss_pct": 8.0,
    "target_profit_pct": 25.0,
    "max_single_position_pct": 20.0
  },
  "transactions": [
    {
      "transaction_id": "txn_000001",
      "external_id": null,
      "transaction_type": "OPENING_POSITION",
      "symbol": "SOFI",
      "shares": 59.0,
      "price": 17.5,
      "amount": null,
      "fees": 0.0,
      "executed_at": null,
      "effective_at": "2026-06-22T16:35:09Z",
      "recorded_at": "2026-06-22T16:35:09Z",
      "source": "legacy_migration",
      "note": "根据系统启用时的真实持仓快照建立，不代表原始逐笔成交记录。"
    },
    {
      "transaction_id": "txn_000002",
      "external_id": null,
      "transaction_type": "OPENING_POSITION",
      "symbol": "SPCX",
      "shares": 2.0,
      "price": 202.0,
      "amount": null,
      "fees": 0.0,
      "executed_at": null,
      "effective_at": "2026-06-22T16:35:09Z",
      "recorded_at": "2026-06-22T16:35:09Z",
      "source": "legacy_migration",
      "note": "根据系统启用时的真实持仓快照建立，不代表原始逐笔成交记录。"
    }
  ]
}
```

### 10.1 示例的运行时校验结果

期初持仓计算：

```text
SOFI shares = 59
SOFI avg_cost = 17.50
SOFI cost_basis = 59 × 17.50 = 1032.50 USD

SPCX shares = 2
SPCX avg_cost = 202.00
SPCX cost_basis = 2 × 202.00 = 404.00 USD

合计 cost_basis = 1032.50 + 404.00 = 1436.50 USD
realized_pnl_since_tracking = 0
cash = null
total_equity = null
```

`OPENING_POSITION` 不改变现金。因为 `cash_status="unknown"`，系统不得显示完整账户总资产；必须先通过券商 API、对账单或人工确认建立可靠现金基线。

## 11. 当前字段迁移对应关系

| 当前字段 | 第一版字段或处理方式 |
|---|---|
| `portfolio.created` | `account.created_at` |
| `portfolio.cash` | 不直接迁移为事实字段；使用初始资金和交易重新核对 |
| `positions[].ticker` | 转换正式交易时使用 `transactions[].symbol` |
| `positions[].shares` | 用于迁移核对，不作为新的持久化持仓字段 |
| `positions[].avg_cost` | 用于迁移核对和补建历史，不作为第二套事实来源 |
| `positions[].added` | 经用户确认后可作为补建交易的 `executed_at` |
| `transactions[].type` | `transactions[].transaction_type`，转换为大写枚举 |
| `transactions[].ticker` | `transactions[].symbol` |
| `transactions[].amount` | 根据原交易类型拆分为 `shares × price` 或新格式 `amount` |
| `transactions[].timestamp` | `transactions[].executed_at` |
| `portfolio_config.total_capital` | 不直接写入账户；与现有现金和交易核对后，由用户确认是否生成期初 `DEPOSIT` |
| `portfolio_config.currency` | `account.base_currency`，第一版必须为 `USD` |
| `portfolio_config.stop_loss_pct` | `settings.stop_loss_pct` |
| `portfolio_config.target_profit_pct` | `settings.target_profit_pct` |
| 代码中的 20% 仓位限制 | `settings.max_single_position_pct` |

正式迁移必须先备份并由用户确认。历史交易不完整时，不能仅凭当前持仓虚构真实交易明细；应设计明确的期初持仓导入流程，并在未来版本中单独规定。
