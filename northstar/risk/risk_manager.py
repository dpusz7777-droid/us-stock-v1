#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风险控制与资金管理系统 — 控制模拟交易资金分配、仓位管理与风险约束。

用法：
    from northstar.risk.risk_manager import RiskManager
    rm = RiskManager(initial_capital=100000)
    size = rm.calculate_position_size(confidence=0.85, price=100.0)
    allowed = rm.check_risk_limits(portfolio_state)
"""

from __future__ import annotations

from typing import Any

RISK_LEVELS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class RiskManager:
    """风险控制管理器。

    仓位规则：
    - confidence > 0.8 → 20%仓位
    - 0.5~0.8 → 10%仓位
    - < 0.5 → 5%仓位
    - 风险状态下整体仓位减半

    风控规则：
    - 单日亏损超过3% → 禁止新开仓
    - 总回撤超过10% → 所有新仓位减半
    - 连续3笔亏损 → 降低整体风险等级
    - 连续3笔盈利 → 小幅提高仓位但不超过上限
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        max_position_pct: float = 0.2,
        max_daily_loss_pct: float = 0.03,
        max_total_drawdown_pct: float = 0.1,
    ) -> None:
        self.initial_capital: float = initial_capital
        self.max_position_pct: float = max_position_pct
        self.max_daily_loss_pct: float = max_daily_loss_pct
        self.max_total_drawdown_pct: float = max_total_drawdown_pct

        # 运行时状态
        self.risk_level: str = "LOW"
        self.capital: float = initial_capital
        self.daily_pnl: list[float] = []
        self.consecutive_losses: int = 0
        self.consecutive_wins: int = 0
        self.total_drawdown_pct: float = 0.0
        self.peak_capital: float = initial_capital
        self.exposure_history: list[dict] = []
        self.risk_events: list[dict] = []
        self._position_utilization: float = 0.0
        self._today_loss: float = 0.0

    def calculate_position_size(
        self,
        confidence: float,
        price: float,
    ) -> float:
        """根据置信度动态计算仓位。

        Returns:
            用于该笔交易的资金金额
        """
        # 基础仓位比例
        if confidence > 0.8:
            base_pct = self.max_position_pct  # 20%
        elif confidence >= 0.5:
            base_pct = self.max_position_pct * 0.5  # 10%
        else:
            base_pct = self.max_position_pct * 0.25  # 5%

        # 风险状态仓位减半
        if self.risk_level == "HIGH":
            base_pct *= 0.5
        elif self.risk_level == "MEDIUM":
            base_pct *= 0.75

        # 总回撤超过10% → 新仓位减半
        if self.total_drawdown_pct >= self.max_total_drawdown_pct:
            base_pct *= 0.5

        # 连续盈利奖励
        if self.consecutive_wins >= 3:
            base_pct = min(base_pct * 1.2, self.max_position_pct)

        position_value = self.capital * base_pct
        return round(position_value, 2)

    def check_risk_limits(self, portfolio_state: dict | None = None) -> bool:
        """检查是否允许开仓。

        Returns:
            True=允许开仓, False=禁止开仓
        """
        # 单日亏损超过3% → 禁止新开仓
        if abs(self._today_loss) >= self.max_daily_loss_pct * self.capital:
            self._add_risk_event("单日亏损超限", f"今日亏损 ${self._today_loss:.0f}")
            return False

        # 总回撤超过10% → 禁止新开仓
        if self.total_drawdown_pct >= self.max_total_drawdown_pct:
            self._add_risk_event("总回撤超限", f"回撤 {self.total_drawdown_pct:.1f}%")
            return False

        return True

    def adjust_exposure(self, drawdown: float) -> float:
        """根据回撤动态降低仓位比例。

        Returns:
            调整后的仓位乘数 (0.0~1.0)
        """
        if drawdown >= self.max_total_drawdown_pct:
            return 0.5
        if drawdown >= self.max_total_drawdown_pct * 0.7:
            return 0.7
        return 1.0

    def allocate_capital(self, signal: dict) -> float:
        """为单个交易信号分配资金。

        Args:
            signal: 信号字典，需包含 confidence

        Returns:
            分配的金额
        """
        confidence = signal.get("confidence", 0.5)
        price = 1.0  # 外部传入实际价格
        return self.calculate_position_size(confidence, price)

    def record_trade_result(self, pnl_pct: float) -> None:
        """记录交易结果，更新风险状态。

        Args:
            pnl_pct: 交易收益率百分比
        """
        # 更新连续盈亏计数
        if pnl_pct > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl_pct < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

        # 连续3笔亏损 → 提高风险等级
        if self.consecutive_losses >= 3:
            old_level = self.risk_level
            self.risk_level = "HIGH"
            if old_level != "HIGH":
                self._add_risk_event("风险等级提升", f"连续{self.consecutive_losses}笔亏损")

        # 连续3笔盈利 → 小幅降低风险等级
        if self.consecutive_wins >= 3 and self.risk_level == "HIGH":
            self.risk_level = "MEDIUM"
        elif self.consecutive_wins >= 3 and self.risk_level == "MEDIUM":
            self.risk_level = "LOW"

    def update_portfolio(self, capital: float, drawdown_pct: float) -> None:
        """更新组合状态。

        Args:
            capital: 当前总资金
            drawdown_pct: 当前回撤百分比
        """
        self.capital = capital
        self.total_drawdown_pct = drawdown_pct

        # 跟踪峰值
        if capital > self.peak_capital:
            self.peak_capital = capital

        # 记录每日仓位变化
        self.exposure_history.append({
            "capital": round(capital, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "risk_level": self.risk_level,
        })

    def record_daily_pnl(self, pnl: float) -> None:
        """记录每日盈亏。"""
        self.daily_pnl.append(pnl)
        if pnl < 0:
            self._today_loss += abs(pnl)
        else:
            self._today_loss = max(0.0, self._today_loss - pnl)

    def get_risk_metrics(self) -> dict[str, Any]:
        """获取风险指标摘要。"""
        # 仓位利用率
        util = self._position_utilization

        return {
            "risk_level": self.risk_level,
            "max_drawdown_pct": round(self.total_drawdown_pct, 2),
            "position_utilization": round(util, 2),
            "can_trade_today": self.check_risk_limits(),
            "consecutive_losses": self.consecutive_losses,
            "consecutive_wins": self.consecutive_wins,
            "recent_risk_events": self.risk_events[-5:][::-1],
        }

    def can_open_new_position(self) -> bool:
        """快捷方法：是否可以开新仓。"""
        return self.check_risk_limits()

    def _add_risk_event(self, event_type: str, detail: str) -> None:
        """添加风险事件到历史。"""
        from datetime import datetime
        self.risk_events.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": event_type,
            "detail": detail,
            "risk_level": self.risk_level,
        })

    def set_position_utilization(self, utilized: float, total: float) -> None:
        """设置仓位利用率。"""
        self._position_utilization = round(utilized / total, 2) if total > 0 else 0.0

    def reset(self) -> None:
        """重置所有状态。"""
        self.risk_level = "LOW"
        self.capital = self.initial_capital
        self.daily_pnl = []
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.total_drawdown_pct = 0.0
        self.peak_capital = self.initial_capital
        self.exposure_history = []
        self.risk_events = []
        self._position_utilization = 0.0
        self._today_loss = 0.0