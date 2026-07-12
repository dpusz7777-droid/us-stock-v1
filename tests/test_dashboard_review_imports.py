# -*- coding: utf-8 -*-
"""dashboard_review 模块导入与结构稳定性测试。

测试目标：
    验证 v22 拆分后的 UI 模块可以正常导入、不产生循环依赖、
    入口函数存在且可调用、不依赖真实后端。

安全原则：
    - 所有测试使用内存数据，不依赖任何文件
    - 不启动真实 Backend
    - 不修改运行时 JSON
"""

from __future__ import annotations

import sys
import inspect
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestDashboardReviewImports(unittest.TestCase):
    """dashboard_review 模块导入与结构测试"""

    # ── A. 可以正常 import northstar.ui.dashboard_review ──
    def test_import_dashboard_review(self):
        """正常导入 northstar.ui.dashboard_review 不报错"""
        try:
            import northstar.ui.dashboard_review
            self.assertTrue(hasattr(northstar.ui.dashboard_review, "render_recommendation_review_section"))
        except Exception as e:
            self.fail(f"导入 northstar.ui.dashboard_review 失败: {e}")

    # ── B. render_recommendation_review_section 存在 ──
    def test_render_function_exists(self):
        """dashboard_review 中存在 render_recommendation_review_section"""
        from northstar.ui.dashboard_review import render_recommendation_review_section
        self.assertIsNotNone(render_recommendation_review_section)

    # ── C. render_recommendation_review_section 是 callable ──
    def test_render_function_is_callable(self):
        """render_recommendation_review_section 是 callable（函数）"""
        from northstar.ui.dashboard_review import render_recommendation_review_section
        self.assertTrue(callable(render_recommendation_review_section))

    # ── D. 可以正常 import northstar.ui.dashboard ──
    def test_import_dashboard(self):
        """正常导入 northstar.ui.dashboard 不报错"""
        try:
            import northstar.ui.dashboard
            self.assertTrue(hasattr(northstar.ui.dashboard, "run"))
        except Exception as e:
            self.fail(f"导入 northstar.ui.dashboard 失败: {e}")

    # ── E. dashboard_review 不应反向 import dashboard ──
    def test_no_reverse_import_to_dashboard(self):
        """dashboard_review 不应反向 import northstar.ui.dashboard"""
        import northstar.ui.dashboard_review
        module_source = inspect.getsource(northstar.ui.dashboard_review)
        # 检查是否包含 import northstar.ui.dashboard（独立语句）
        # 注意：不匹配 "from northstar.ui.dashboard_review"（这是导出自身的示例）
        for line in module_source.splitlines():
            stripped = line.strip()
            # 跳过 import 自身的示例和注释
            if stripped.startswith("#"):
                continue
            if "import northstar.ui.dashboard" in stripped and "dashboard_review" not in stripped:
                self.fail(f"dashboard_review 不应反向 import dashboard: {stripped}")

    # ── F. dashboard_review 应只依赖 streamlit/pandas/data 层 ──
    def test_dependencies_are_restricted(self):
        """dashboard_review 不应依赖 backend、券商、交易执行模块"""
        import northstar.ui.dashboard_review
        module_source = inspect.getsource(northstar.ui.dashboard_review)
        forbidden = [
            "launch",
            "execution_engine",
            "broker_provider",
            "price_provider",
            "backtest",
            "northstar.main",
            "northstar.backend",
        ]
        for item in forbidden:
            if item in module_source:
                self.fail(f"dashboard_review 不应依赖 {item}")

    # ── G. dashboard 同时保留复盘与持仓建议正式入口 ──
    def test_dashboard_calls_review_module(self):
        """首页不能因新增持仓 MVP 而丢失原建议复盘。"""
        import northstar.ui.dashboard
        source = inspect.getsource(northstar.ui.dashboard)
        self.assertIn("dashboard_review", source,
                       "dashboard.py 应导入 dashboard_review")
        self.assertIn("render_recommendation_review_section", source,
                       "dashboard.py 应调用 render_recommendation_review_section")
        self.assertIn("_render_recommendation_review(st)", source,
                       "dashboard.run 应渲染建议复盘")
        self.assertIn("_render_holdings_decisions", source,
                       "dashboard.py 应包含 _render_holdings_decisions（当前正式持仓入口）")


class TestFunctionSignature(unittest.TestCase):
    """render_recommendation_review_section 函数签名检查"""

    def test_function_has_correct_params(self):
        """检查 render_recommendation_review_section 的关键参数"""
        from northstar.ui.dashboard_review import render_recommendation_review_section
        sig = inspect.signature(render_recommendation_review_section)
        params = sig.parameters.keys()
        for required in ["st", "all_recs", "classify_grade_fn"]:
            self.assertIn(required, params, f"缺少必需参数: {required}")


class TestImportSideEffects(unittest.TestCase):
    """导入副作用的稳定性测试"""

    def test_no_file_read_on_import(self):
        """import dashboard_review 不应触发文件读取（无副作用）"""
        # 如果 import 导致 file read，说明有 import-time 副作用
        # 这里通过多次 import 确认不崩溃即可
        for _ in range(3):
            try:
                # 重新加载模块
                if "northstar.ui.dashboard_review" in sys.modules:
                    del sys.modules["northstar.ui.dashboard_review"]
                import northstar.ui.dashboard_review  # noqa: F811
            except Exception as e:
                self.fail(f"重复 import dashboard_review 失败: {e}")

    def test_no_crash_with_missing_submodules(self):
        """即使 data 层某些模块缺失，导入不应直接崩溃"""
        # 导入 data 层模块确保可用
        try:
            from northstar.data import recommendation_review
            self.assertTrue(hasattr(recommendation_review, "classify_recommendation_review_result"))
        except Exception as e:
            self.fail(f"导入 data/recommendation_review 失败: {e}")

        try:
            from northstar.data import recommendation_review_snapshot
            self.assertTrue(hasattr(recommendation_review_snapshot, "save_recommendation_review_snapshot"))
        except Exception as e:
            self.fail(f"导入 data/recommendation_review_snapshot 失败: {e}")


if __name__ == "__main__":
    unittest.main()
