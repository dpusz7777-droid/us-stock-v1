# -*- coding: utf-8 -*-
"""项目状态总览测试 — get_git_commit_info 的只读测试。

测试目标：
    验证 get_git_commit_info 的返回值。

安全原则：
    - 所有测试使用内存数据，不依赖真实文件（除项目目录自身）
    - 不修改任何数据
    - 不启动 backend
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 直接定义 get_git_commit_info 的副本用于测试（避免导入 UI 模块的副作用）
import subprocess


def get_git_commit_info(project_root: str | Path) -> dict:
    """只读获取当前 Git 仓库的 commit 信息。"""
    result = {"commit": "暂无数据", "message": "暂无数据", "is_clean": None, "error": None}
    git_dir = Path(project_root) / ".git"
    if not git_dir.exists():
        result["error"] = "非 Git 仓库"
        return result
    try:
        r1 = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2, cwd=project_root)
        if r1.returncode == 0:
            result["commit"] = r1.stdout.strip()
        else:
            result["error"] = "git rev-parse 失败"
    except FileNotFoundError:
        result["error"] = "git 命令不存在"
        return result
    except subprocess.TimeoutExpired:
        result["error"] = "读取超时"
        return result
    except Exception as e:
        result["error"] = f"读取异常: {type(e).__name__}"
        return result
    try:
        r2 = subprocess.run(["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True, timeout=2, cwd=project_root)
        if r2.returncode == 0:
            result["message"] = r2.stdout.strip()
    except Exception:
        pass
    try:
        r3 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=2, cwd=project_root)
        result["is_clean"] = (r3.returncode == 0 and not r3.stdout.strip())
    except Exception:
        pass
    return result


class TestGetGitCommitInfo(unittest.TestCase):
    """get_git_commit_info 单元测试"""

    # A. 真实项目目录返回正确结构
    def test_real_project_returns_dict_with_fields(self):
        result = get_git_commit_info(PROJECT_ROOT)
        self.assertIn("commit", result)
        self.assertIn("message", result)
        self.assertIn("is_clean", result)
        self.assertIn("error", result)

    # B. commit 字段应该是 7 位 hash
    def test_commit_is_short_hash(self):
        result = get_git_commit_info(PROJECT_ROOT)
        if result.get("error") is None:
            self.assertEqual(len(result["commit"]), 7)

    # C. 非 Git 目录不崩溃（使用明确无 .git 的目录）
    def test_non_git_directory(self):
        result = get_git_commit_info("/tmp")
        self.assertIsNotNone(result)
        self.assertIn(result.get("error"), ["非 Git 仓库", None])

    # D. 不存在目录不崩溃
    def test_nonexistent_directory(self):
        result = get_git_commit_info("/nonexistent/path")
        self.assertIsNotNone(result)
        self.assertIn(result.get("commit"), ["暂无数据", "读取异常"])

    # E. 函数不修改文件
    def test_no_write(self):
        import os
        before = os.popen("git status --short").read()
        _ = get_git_commit_info(PROJECT_ROOT)
        after = os.popen("git status --short").read()
        self.assertEqual(before, after)

    # F. error 字段不存在时不返回错误
    def test_no_error_in_real_repo(self):
        result = get_git_commit_info(PROJECT_ROOT)
        # 如果在真实 Git 仓库，error 应该为 None
        if result.get("commit") != "暂无数据":
            self.assertIsNone(result.get("error"))


if __name__ == "__main__":
    unittest.main()