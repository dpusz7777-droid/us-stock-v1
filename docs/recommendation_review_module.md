# 北极星建议复盘模块说明

## 1. 模块定位

- 本模块只做**历史建议记录、复盘、统计与质量解释**
- **不自动交易**
- **不写回券商**
- **不构成投资建议**
- 所有结论仅用于**历史复盘验证**
- 所有函数保持**只读原则**（除非是专门的建议留痕写入功能）

---

## 2. 当前功能范围

| 功能 | 说明 | 对应版本 |
|------|------|---------|
| 建议留痕 | 记录/新增系统建议（买入、卖出、持有等） | v0 |
| 建议复盘 | 计算每条建议从记录时到现在的涨跌幅、复盘状态 | v1 |
| 单条建议分级 | 有效 / 失效 / 待观察 / 数据不足 | v14 |
| 复盘决策看板 | 当前筛选结果的总有效率和分级分布 | v14 |
| 复盘质量解释 | 样本质量等级、主要问题、下一步建议 | v17 |
| 分级筛选/排序 | 按分级筛选、按分级优先级排序 | v18 |
| 失效原因归类 | 买入后下跌 / 卖出后上涨 / 数据不足等 | v19 |
| 失效原因分布 | 各失效原因数量和严重程度分布 | v19 |
| 复盘结论总览 | 失效分析结论和后续复盘建议 | v20 |
| 数据体检 | 检查建议数据的完整性（缺字段、缺价格等） | v13 |
| 复盘快照 | 保存、查询复盘统计快照 | v13 |
| 复盘趋势 | 方向胜率、涨跌幅、样本数趋势图 | v13 |
| 分级趋势 | 有效/失效数量、有效率趋势图 | v16 |
| 失效原因趋势 | 失效原因统计的跨快照趋势提示 | v20 |

---

## 3. 代码结构

```
northstar/
├── data/
│   ├── recommendation_review.py          复盘计算、分级、质量解释、失效原因
│   ├── recommendation_review_snapshot.py  快照读写、趋势计算、grade_stats/failure_stats
│   └── recommendation_store.py           建议增删改查（留痕）
├── ui/
│   ├── dashboard.py                      主仪表盘（只调用复盘 UI 模块）
│   └── dashboard_review.py               复盘 UI 渲染入口（v22 拆分）
tests/
├── test_recommendation_review_grading.py              v15 分级规则测试
├── test_recommendation_review_snapshot_grading.py     v16.1 快照分级测试
├── test_recommendation_review_quality_explanation.py  v17 质量解释测试
├── test_recommendation_failure_reason.py              v19 失效原因测试
├── test_recommendation_failure_summary.py             v20 失效统计测试
└── test_dashboard_review_imports.py                   v23 导入稳定性测试
```

### 文件职责

| 文件 | 行数 | 主要职责 |
|------|------|---------|
| `data/recommendation_review.py` | ~1990 | 复盘计算、分级、质量解释、失效原因、统计 |
| `data/recommendation_review_snapshot.py` | ~360 | 快照读写、趋势计算、grade_stats/failure_stats |
| `ui/dashboard_review.py` | ~580 | 复盘 UI 渲染入口（v22 从 dashboard.py 拆分） |
| `ui/dashboard.py` | ~370 | 主仪表盘，只调用复盘 UI 模块 |

---

## 4. 关键函数说明

### data/recommendation_review.py

#### `review_recommendations(recommendations)`
- **输入**：建议记录列表 `list[dict]`
- **输出**：复盘结果列表，增加 `current_price`、`change`、`change_pct`、`days_since`、`due_for_review`、`review_status` 等字段
- **只读**：✅ 是
- **用途**：对每条建议计算当前价格和涨跌幅

#### `classify_recommendation_review_result(row)`
- **输入**：单条复盘记录 `dict`
- **输出**：`{"review_grade", "review_grade_reason", "review_grade_score"}`
- **只读**：✅ 是
- **用途**：将建议分为 有效 / 失效 / 待观察 / 数据不足
- **规则**：基于 ±3% 涨跌幅阈值

#### `build_recommendation_review_quality_explanation(review_rows)`
- **输入**：复盘记录列表 `list[dict]`
- **输出**：`{"quality_level", "main_issue", "explanation", "next_action", "warning_flags"}`
- **只读**：✅ 是
- **用途**：评估当前复盘样本质量，给出人话解释

#### `classify_recommendation_failure_reason(row)`
- **输入**：单条复盘记录 `dict`
- **输出**：`{"failure_reason", "failure_reason_detail", "failure_severity", "failure_flags"}`
- **只读**：✅ 是
- **用途**：对失效建议自动归类原因（买入后下跌 / 卖出后上涨 / 数据不足 / 动作无法识别）

#### `build_failure_reason_summary(review_rows)`
- **输入**：复盘记录列表 `list[dict]`
- **输出**：`{"total_failed_count", "reason_counts", "severity_counts", "top_failure_reason", "top_failure_ratio", "conclusion", "next_action"}`
- **只读**：✅ 是
- **用途**：失效原因统计总览和结论

#### `_is_buy_action(action)` / `_is_sell_action(action)`
- **输入**：建议动作字符串
- **输出**：`bool`
- **只读**：✅ 是
- **用途**：统一的中英文动作识别函数

### data/recommendation_review_snapshot.py

#### `compute_grade_stats_from_overall(overall_stats)`
- **输入**：overall stats dict
- **输出**：`{"grade_valid_count", "grade_watch_count", "grade_invalid_count", "grade_insufficient_count", "grade_effective_rate", "grade_sample_count"}`
- **只读**：✅ 是
- **用途**：从统计结果计算分级统计（兼容旧快照）

#### `save_recommendation_review_snapshot(...)`
- **只读**：✅ 是（写快照文件，但不写回 recommendations.json）
- **用途**：保存一条复盘快照

#### `get_recommendation_review_snapshot_trend(limit)`
- **只读**：✅ 是
- **用途**：返回快照趋势数据（含 grade_stats 字段）

### ui/dashboard_review.py

#### `render_recommendation_review_section(...)`
- **只读**：✅ 是（不写回任何文件，仅渲染 UI）
- **用途**：渲染所有建议复盘相关 UI 区域
- **参数**：接收 data 层函数作为回调，不直接依赖 data 模块

---

## 5. 快照字段说明

### grade_stats（v16 新增，向下兼容）

```json
{
  "grade_valid_count": 2,
  "grade_watch_count": 3,
  "grade_invalid_count": 1,
  "grade_insufficient_count": 4,
  "grade_effective_rate": 66.7,
  "grade_sample_count": 3
}
```

**兼容原则**：旧快照没有这些字段时，`compute_grade_stats_from_overall` 返回 `None`，UI 显示友好提示。

### failure_stats（v20 新增，向下兼容）

```json
{
  "total_failed_count": 5,
  "reason_counts": {"买入后下跌": 3, "卖出后上涨": 2},
  "severity_counts": {"高": 1, "中": 2, "低": 2},
  "top_failure_reason": "买入后下跌",
  "top_failure_ratio": 0.6
}
```

**兼容原则**：旧快照没有 `failure_stats` 字段时，趋势区域显示引导提示，不会崩溃。

---

## 6. 测试说明

### 测试文件列表

| 测试文件 | 测试数量 | 覆盖内容 |
|---------|---------|---------|
| `tests/test_recommendation_review_grading.py` | 17 | 分级规则（有效/失效/待观察/数据不足） |
| `tests/test_recommendation_review_snapshot_grading.py` | 13 | 快照 grade_stats、旧快照兼容 |
| `tests/test_recommendation_review_quality_explanation.py` | 10 | 质量解释规则（空数据/集中/分散） |
| `tests/test_recommendation_failure_reason.py` | 15 | 失效原因归类（买入/卖出/缺失字段） |
| `tests/test_recommendation_failure_summary.py` | 8 | 失效统计总览（集中/分散/高严重） |
| `tests/test_dashboard_review_imports.py` | 10 | 导入稳定性、循环依赖检查 |

### 运行命令

```bash
# 单模块测试
.venv/bin/python -m unittest tests.test_recommendation_review_grading -v
.venv/bin/python -m unittest tests.test_recommendation_review_snapshot_grading -v
.venv/bin/python -m unittest tests.test_recommendation_review_quality_explanation -v
.venv/bin/python -m unittest tests.test_recommendation_failure_reason -v
.venv/bin/python -m unittest tests.test_recommendation_failure_summary -v
.venv/bin/python -m unittest tests.test_dashboard_review_imports -v

# 全量测试
.venv/bin/python -m unittest discover -s tests -v
```

---

## 7. 开发原则

1. **不自动交易** — 本模块任何函数不得触发真实交易
2. **不写回 recommendations.json** — 除非是专门的建议留痕写入功能（`add_recommendation`）
3. **不修改真实持仓数据** — 持仓数据只能由持仓管理模块修改
4. **不提交 logs、.venv、缓存文件** — `.gitignore` 已保护
5. **data 层不能依赖 UI 层** — `data/recommendation_review.py` 和 `data/recommendation_review_snapshot.py` 不应 `import northstar.ui.*`
6. **UI 模块不能启动 backend** — `dashboard_review.py` 只渲染 UI，不启动任何后台进程
7. **所有复盘结论仅用于历史复盘验证，不构成投资建议**
8. **旧快照必须兼容** — 新字段必须可选，旧快照缺字段时不能崩溃
9. **函数保持只读（除非设计上需要写入）** — 所有计算函数不修改输入数据

---

## 8. 后续开发建议

1. **统一 action 识别** — 当前 `infer_recommendation_action()`、`_is_buy_action()`、`_is_sell_action()` 有三套关键词集合，建议合并
2. **快照自动保存策略** — 在 backend 中增加定时自动保存快照逻辑
3. **失效原因趋势图增强** — 当 failure_stats 积累足够时，绘制多类原因的对比趋势看板
4. **复盘模块多页面化** — 当 dashboard_review.py 继续增长时，可拆为多页面
5. **报告导出** — 支持将复盘结论导出为 Markdown 或 HTML