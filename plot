#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B1: 回测可视化脚本。

构造示例数据，运行回测，绘制收益曲线。
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import matplotlib.pyplot as plt

from backtest_engine import BacktestEngine


def main() -> None:
    """运行回测可视化演示。"""

    # ---------------------------------------------------------------
    # 1. 构造示例数据（AAPL，≥5 个时间点）
    #    每个元素: (price: Decimal, timestamp: str)
    # ---------------------------------------------------------------
    ts_base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    sample_data: list[tuple[Decimal, str]] = [
        (Decimal("150.00"), ts_base.replace(day=1).isoformat()),
        (Decimal("152.00"), ts_base.replace(day=2).isoformat()),
        (Decimal("149.50"), ts_base.replace(day=3).isoformat()),
        (Decimal("151.00"), ts_base.replace(day=4).isoformat()),
        (Decimal("153.50"), ts_base.replace(day=5).isoformat()),
        (Decimal("155.00"), ts_base.replace(day=6).isoformat()),
        (Decimal("154.20"), ts_base.replace(day=7).isoformat()),
        (Decimal("158.00"), ts_base.replace(day=8).isoformat()),
        (Decimal("160.00"), ts_base.replace(day=9).isoformat()),
        (Decimal("157.50"), ts_base.replace(day=10).isoformat()),
    ]

    print("=" * 60)
    print("  B1 回测可视化演示")
    print("=" * 60)
    print(f"  股票: AAPL")
    print(f"  数据点数: {len(sample_data)}")
    print(f"  起始价: ${sample_data[0][0]}")
    print(f"  结束价: ${sample_data[-1][0]}")
    print()

    # ---------------------------------------------------------------
    # 2. 运行回测
    # ---------------------------------------------------------------
    engine = BacktestEngine(initial_cash=Decimal("100000"))

    # 使用 run() 可支持多股票，这里只跑单票
    multi_result = engine.run({"AAPL": sample_data})
    aapl_result = multi_result.symbol_results["AAPL"]

    # ---------------------------------------------------------------
    # 3. 获取 equity curve
    # ---------------------------------------------------------------
    equity_curve = engine.get_equity_curve()
    if not equity_curve:
        # 回退使用 result 里的 equity_curve
        equity_curve = aapl_result.equity_curve

    # ---------------------------------------------------------------
    # 4. 打印回测摘要
    # ---------------------------------------------------------------
    print("-" * 40)
    print("  回测摘要")
    print("-" * 40)
    print(f"  初始资金:     ${aapl_result.initial_cash:,.2f}")
    print(f"  最终净值:     ${aapl_result.final_equity:,.2f}")
    print(f"  总收益率:     {float(aapl_result.total_return_pct):+.2f}%")
    print(f"  最大回撤:     {float(aapl_result.max_drawdown):.2f}%")
    print(f"  交易次数:     {aapl_result.trade_count}")
    print(f"  胜率:         {aapl_result.win_rate:.1%}")
    print(f"  盈亏比:       {aapl_result.profit_loss_ratio:.2f}")
    print(f"  权益曲线长度: {len(equity_curve)} 步")
    print()

    # ---------------------------------------------------------------
    # 5. 绘图
    # ---------------------------------------------------------------
    # 转换为 float 以便 matplotlib 绘制
    equity_values = [float(e) for e in equity_curve]

    plt.figure(figsize=(10, 5))
    plt.plot(equity_values, marker="o", linewidth=2, markersize=4, color="#1f77b4")
    plt.title("Equity Curve (Backtest)")
    plt.xlabel("Time Step")
    plt.ylabel("Portfolio Value ($)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # 添加起始资金参考线
    initial_value = float(aapl_result.initial_cash)
    plt.axhline(
        y=initial_value, color="gray", linestyle="--", linewidth=1, alpha=0.7,
        label=f"Initial (${initial_value:,.0f})"
    )
    plt.legend()

    # 保存图片
    output_path = "reports/equity_curve.png"
    plt.savefig(output_path, dpi=150)
    print(f"  图表已保存至: {output_path}")

    plt.show()


if __name__ == "__main__":
    main()