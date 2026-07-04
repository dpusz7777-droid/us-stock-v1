#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准事件名称定义。

本模块定义系统级标准事件名称，供 EventBus publish / subscribe 使用。
事件名使用大写加下划线格式。

安全说明
---------
- 事件定义本身不包含任何业务逻辑
- 不访问网络、不写文件、不读取敏感信息
- 只定义常量字符串
"""

# --- PriceProvider 事件 ---
# 行情数据更新后发布
MARKET_DATA_UPDATED = "MARKET_DATA_UPDATED"

# --- BrokerProvider 事件 ---
# 券商快照更新后发布
BROKER_SNAPSHOT_UPDATED = "BROKER_SNAPSHOT_UPDATED"

# --- 简报事件 ---
# morning / evening / ai 简报生成后发布
BRIEFING_GENERATED = "BRIEFING_GENERATED"

# --- 持仓事件 ---
# 持仓数据更新后发布
PORTFOLIO_UPDATED = "PORTFOLIO_UPDATED"

# --- Dashboard 事件 ---
# Dashboard 刷新时发布
DASHBOARD_REFRESH = "DASHBOARD_REFRESH"

# --- 系统事件 ---
# 系统健康检查完成后发布
SYSTEM_HEALTH_CHECK = "SYSTEM_HEALTH_CHECK"

# --- 信号事件 ---
# SignalEngine 生成信号后发布
SIGNAL_GENERATED = "SIGNAL_GENERATED"

# --- 风控事件 ---
# RiskEngine 完成风控评估后发布
RISK_EVALUATED = "RISK_EVALUATED"

# --- 市场状态事件 ---
# MarketRegimeEngine 检测到市场状态变化后发布
MARKET_REGIME_UPDATED = "MARKET_REGIME_UPDATED"
# DecisionEngine 使用了 MarketRegime 进行决策
MARKET_REGIME_USED = "MARKET_REGIME_USED"

# --- 仓位事件 ---
# PositionEngine 计算仓位后发布
POSITION_CALCULATED = "POSITION_CALCULATED"

# --- 资金保护事件 ---
# CapitalGuard 评估资金状态后发布
CAPITAL_MODE_UPDATED = "CAPITAL_MODE_UPDATED"

# --- 策略事件 ---
# StrategyEngine 选择策略后发布
STRATEGY_SELECTED = "STRATEGY_SELECTED"
# StrategyOptimizer 更新策略权重后发布
STRATEGY_WEIGHT_UPDATED = "STRATEGY_WEIGHT_UPDATED"
# LiveLearningEngine 完成自适应更新后发布
LIVE_LEARNING_UPDATED = "LIVE_LEARNING_UPDATED"

# --- 决策事件 ---
# DecisionEngine 生成最终决策后发布
DECISION_CREATED = "DECISION_CREATED"

# --- 执行事件 ---
# ExecutionEngine 处理订单时发布
ORDER_SUBMITTED = "ORDER_SUBMITTED"
ORDER_FILLED = "ORDER_FILLED"
ORDER_REJECTED = "ORDER_REJECTED"

# --- Pipeline 事件 ---
PIPELINE_STARTED = "PIPELINE_STARTED"
PIPELINE_STEP_COMPLETED = "PIPELINE_STEP_COMPLETED"
PIPELINE_BLOCKED = "PIPELINE_BLOCKED"
PIPELINE_COMPLETED = "PIPELINE_COMPLETED"
PIPELINE_FAILED = "PIPELINE_FAILED"

# --- 错误事件 ---
# 系统级错误发生时发布
ERROR_OCCURRED = "ERROR_OCCURRED"

# 所有标准事件集合
ALL_EVENTS = frozenset({
    MARKET_DATA_UPDATED,
    BROKER_SNAPSHOT_UPDATED,
    BRIEFING_GENERATED,
    PORTFOLIO_UPDATED,
    DASHBOARD_REFRESH,
    SIGNAL_GENERATED,
    RISK_EVALUATED,
    MARKET_REGIME_UPDATED,
    MARKET_REGIME_USED,
    POSITION_CALCULATED,
    CAPITAL_MODE_UPDATED,
    STRATEGY_SELECTED,
    STRATEGY_WEIGHT_UPDATED,
    LIVE_LEARNING_UPDATED,
    PIPELINE_STARTED,
    PIPELINE_STEP_COMPLETED,
    PIPELINE_BLOCKED,
    PIPELINE_COMPLETED,
    PIPELINE_FAILED,
    DECISION_CREATED,
    ORDER_SUBMITTED,
    ORDER_FILLED,
    ORDER_REJECTED,
    SYSTEM_HEALTH_CHECK,
    ERROR_OCCURRED,
})
