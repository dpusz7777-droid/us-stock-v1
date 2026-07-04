"""北极星 v2.5 UI 层 — 独立前端服务。

UI 是独立服务层 (independent service layer)：
    - 通过 subprocess 由 launch.py 启动
    - 不共享 streamlit runtime 与 backend
    - 只读模式：仅 render data / show reports
    - 禁止调用 safe_dispatch、safe_execute、backend start
    - 禁止 open browser

入口: dashboard.py
"""