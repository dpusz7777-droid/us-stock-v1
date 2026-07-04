"""北极星 v2.5 系统核心层 — 单例 + 调度器 + 看门狗 + 状态管理。

包含：
    - singleton.py  — 进程级 PID 单例守卫
    - dispatcher.py — 安全事件调度器
    - watchdog.py   — 守护进程监控
    - state.py      — 全局状态管理
"""