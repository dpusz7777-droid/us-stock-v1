#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星 Northstar — 架构重构入口。

新版目录结构：
    /northstar
        /core/       — 信号 + 策略 + 风控
        /data/       — 市场数据 + 持仓 + 历史操作
        /report/     — 报告生成 + 模板
        /backtest/   — 模拟盘 + 评估
        /interface/  — API预留
"""

from __future__ import annotations