from typing import Any

def guard_execution(*args: Any, **kwargs: Any) -> Any:
    """
    临时安全保护模块：
    作用：防止 UI 因缺少 execution_guard 模块而崩溃。
    当前只做只读保护，不执行任何真实交易。
    """
    if args:
        return args[0]
    return []
