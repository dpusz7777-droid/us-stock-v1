#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B1: 回测脚本（无外部依赖版本）。

构造示例数据，运行回测，输出 equity curve 数据。
不依赖 matplotlib 或任何第三方包，纯 Python 标准库。
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

from backtest_engine import BacktestEngine


def main() -> None:
    """运行回测并输出 equity curve 数据。"""

    # ---------------------------------------------------------------
    # 1. 构造示例数据（AAPL，>=5 个时间点）
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
    print("  B1 回测（无外部依赖版本）")
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
    multi_result = engine.run({"AAPL": sample_data})

    # ---------------------------------------------------------------
    # 3. 获取 equity curve
    # ---------------------------------------------------------------
    equity_curve = engine.get_equity_curve()

    # ---------------------------------------------------------------
    # 4. 输出 Equity Curve
    # ---------------------------------------------------------------
    print("Equity Curve:")
    equity_floats = [float(e) for e in equity_curve]
    print(equity_floats)
    print()

    # ---------------------------------------------------------------
    # 5. 输出最终结果
    # ---------------------------------------------------------------
    aapl_result = multi_result.symbol_results["AAPL"]
    print(f"Final Value:")
    print(f"{float(aapl_result.final_equity):.2f}")
    print()
    print(f"Steps:")
    print(f"{len(equity_curve)}")


if __name__ == "__main__":
    main()